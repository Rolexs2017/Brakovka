from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import os
import sys
from time import monotonic

try:
    import pwd
except ImportError:  # Windows
    pwd = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

Button = None
DigitalInputDevice = None
Device = None
_GPIOZERO_IMPORT_ERROR: str | None = None

try:
    from gpiozero import Button as _Button  # type: ignore
    from gpiozero import Device as _Device  # type: ignore
    from gpiozero import DigitalInputDevice as _DigitalInputDevice  # type: ignore

    Button = _Button
    Device = _Device
    DigitalInputDevice = _DigitalInputDevice
except Exception as exc:  # ModuleNotFoundError and broken installs
    _GPIOZERO_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    Button = None
    Device = None
    DigitalInputDevice = None

# gpiozero on non-RPi hosts often fails at runtime (no pin factory / no /dev/gpiomem).
if Button is not None and not sys.platform.startswith("linux"):
    _GPIOZERO_IMPORT_ERROR = f"unsupported platform {sys.platform!r}"
    Button = None

from .config import GpioConfig
from .machine import Inputs


def _gpiochip_ids() -> list[int]:
    """Prefer the main SoC GPIO chip; avoid secondary chips (e.g. gpiochip1)."""
    chips: list[int] = []
    env = os.getenv("GPIOZERO_LGPIO_CHIP", "").strip()
    if env.isdigit():
        return [int(env)]

    # gpiochip4 is often a symlink to the main chip on recent Pi OS / Trixie.
    main = Path("/dev/gpiochip0")
    if main.exists() or Path("/dev/gpiochip4").exists():
        chips.append(0)
    for path in sorted(Path("/dev").glob("gpiochip*")):
        suffix = path.name.removeprefix("gpiochip")
        if not suffix.isdigit():
            continue
        cid = int(suffix)
        # Skip obvious non-main chips unless nothing else is available.
        if cid in (0, 4):
            if cid == 4 and 0 not in chips:
                chips.append(0)
            continue
        if cid not in chips:
            chips.append(cid)
    if not chips:
        chips = [0, 4]
    out: list[int] = []
    seen: set[int] = set()
    for c in chips:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _permission_hint() -> str:
    chips = sorted(Path("/dev").glob("gpiochip*"))
    chip_note = ", ".join(p.name for p in chips) if chips else "нет /dev/gpiochip*"
    if pwd is None:
        user = os.getenv("USERNAME") or os.getenv("USER") or "?"
        groups: set[str] = set()
    else:
        user = pwd.getpwuid(os.getuid()).pw_name
        try:
            import grp

            pw = pwd.getpwuid(os.getuid())
            groups = {grp.getgrgid(g).gr_name for g in os.getgroups()}
            groups.add(grp.getgrgid(pw.pw_gid).gr_name)
        except Exception:
            groups = set()
    group_note = ",".join(sorted(groups)) if groups else "?"
    hint = f"python={sys.executable}; chips=[{chip_note}]; user={user} groups=[{group_note}]"
    if "gpio" not in groups:
        hint += f"; sudo usermod -aG gpio {user} && перелогиньтесь"
    hint += (
        "; sudo apt install -y python3-gpiozero python3-lgpio python3-rpi-lgpio; "
        "убейте второй экземпляр приложения: pkill -f run_brakovka; "
        "export GPIOZERO_PIN_FACTORY=lgpio"
    )
    return hint


def _probe_input(pin: int) -> None:
    """Open one input briefly to validate the selected pin factory."""
    if DigitalInputDevice is None:
        return
    dev = DigitalInputDevice(pin, pull_up=True)
    try:
        _ = bool(dev.is_active)
    finally:
        try:
            dev.close()
        except Exception:
            pass


def _configure_pin_factory(*, probe_pin: int = 23) -> str:
    """
    Pick a pin factory for Raspberry Pi / Debian Trixie.

    Same approach as deploy/check_gpio.sh: prefer lgpio chip0, probe is best-effort.
    """
    if Device is None:
        return "none"

    # Default like the working check script (pigpiod is usually absent on Trixie).
    os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

    preferred = os.getenv("GPIOZERO_PIN_FACTORY", "").strip().lower()
    default_order = ["lgpio", "rpigpio", "native", "pigpio"]
    order: list[str] = []
    if preferred:
        order.append(preferred)
    for name in default_order:
        if name not in order:
            order.append(name)

    errors: list[str] = []
    for name in order:
        try:
            if name in ("lgpio", "lgpiofactory"):
                from gpiozero.pins.lgpio import LGPIOFactory  # type: ignore

                last_exc: Exception | None = None
                for chip in _gpiochip_ids():
                    try:
                        Device.pin_factory = LGPIOFactory(chip=chip)
                        # Best-effort probe; factory may still be usable if pin is busy.
                        try:
                            _probe_input(probe_pin)
                        except Exception as probe_exc:
                            log.warning(
                                "lgpio chip=%s ok, probe GPIO%s failed: %s "
                                "(continue; close other app if pin busy)",
                                chip,
                                probe_pin,
                                probe_exc,
                            )
                        log.info("gpiozero pin factory: lgpio (chip=%s)", chip)
                        return f"lgpio:chip{chip}"
                    except Exception as exc:
                        last_exc = exc
                        log.info("lgpio chip=%s failed: %s", chip, exc)
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("lgpio: no gpiochip found")

            if name in ("rpigpio", "rpi.gpio", "rpigpiofactory"):
                from gpiozero.pins.rpigpio import RPiGPIOFactory  # type: ignore

                Device.pin_factory = RPiGPIOFactory()
                try:
                    _probe_input(probe_pin)
                except Exception as probe_exc:
                    log.warning("rpigpio probe failed: %s", probe_exc)
                log.warning("gpiozero pin factory: rpigpio")
                return "rpigpio"

            if name == "native":
                from gpiozero.pins.native import NativeFactory  # type: ignore

                Device.pin_factory = NativeFactory()
                try:
                    _probe_input(probe_pin)
                except Exception as probe_exc:
                    log.warning("native probe failed: %s", probe_exc)
                log.warning("gpiozero pin factory: native (last resort)")
                return "native"

            if name in ("pigpio", "pi.gpio", "pigpiopinfactory"):
                from gpiozero.pins.pigpio import PiGPIOFactory  # type: ignore

                Device.pin_factory = PiGPIOFactory()
                try:
                    _probe_input(probe_pin)
                except Exception as probe_exc:
                    log.warning("pigpio probe failed: %s", probe_exc)
                log.info("gpiozero pin factory: pigpio")
                return "pigpio"

            errors.append(f"{name}: unknown factory name")
        except Exception as exc:
            msg = f"{name}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            log.info("gpiozero pin factory %s failed: %s", name, exc)
            continue

    raise RuntimeError(
        "No gpiozero pin factory could be loaded. Tried: "
        + "; ".join(errors)
        + ". | "
        + _permission_hint()
    )


@dataclass
class _PulseLatch:
    hold_s: float
    _active_until: float = 0.0

    def latch(self) -> None:
        self._active_until = monotonic() + self.hold_s

    def read(self) -> bool:
        return monotonic() < self._active_until


@dataclass(frozen=True)
class GpioLevels:
    """Raw digital input levels (active = button pressed, active-LOW wiring)."""

    available: bool = False
    start: bool = False
    stop: bool = False
    jog: bool = False
    reverse: bool = False
    reset_wound: bool = False
    pin_start: int = 23
    pin_stop: int = 24
    pin_jog: int = 25
    pin_reverse: int = 8
    pin_reset_wound: int = 7
    error: str = ""
    pin_factory: str = ""


class GpioInputs:
    """
    Physical operator buttons (active LOW, pull_up=True).

    Always opened when gpiozero/RPi GPIO is available — including emulator mode
    (emulator only replaces VFD + encoder, not panel buttons).

    Pulse commands (start/stop/reset_wound) are rising-edge latched by polling
    ``is_pressed`` (no gpiozero edge callbacks — more reliable on Bookworm/Trixie).
    """

    def __init__(self, gpio: GpioConfig | None = None, pulse_hold_s: float = 0.08) -> None:
        gpio = gpio or GpioConfig()
        self._pin_start = int(gpio.btn_start)
        self._pin_stop = int(gpio.btn_stop)
        self._pin_jog = int(gpio.btn_jog)
        self._pin_reverse = int(gpio.btn_reverse)
        self._pin_reset_wound = int(gpio.btn_reset_wound)

        self._start = None
        self._stop = None
        self._jog = None
        self._rev = None
        self._reset_wound = None
        self._available = False
        self._error = ""
        self._pin_factory = ""

        self._start_p = _PulseLatch(pulse_hold_s)
        self._stop_p = _PulseLatch(pulse_hold_s)
        self._reset_wound_p = _PulseLatch(pulse_hold_s)

        self._prev_start = False
        self._prev_stop = False
        self._prev_reset_wound = False

        if Button is None:
            self._error = (
                (_GPIOZERO_IMPORT_ERROR or "gpiozero import failed")
                + " | "
                + _permission_hint()
            )
            log.warning("GPIO buttons disabled: %s", self._error)
            return

        try:
            self._pin_factory = _configure_pin_factory(probe_pin=self._pin_start)
            # No bounce_time: that enables edge detection, which breaks with
            # legacy RPi.GPIO. We poll is_pressed instead.
            self._start = Button(gpio.btn_start, pull_up=True)
            self._stop = Button(gpio.btn_stop, pull_up=True)
            self._jog = Button(gpio.btn_jog, pull_up=True)
            self._rev = Button(gpio.btn_reverse, pull_up=True)
            self._reset_wound = Button(gpio.btn_reset_wound, pull_up=True)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc} | {_permission_hint()}"
            log.exception(
                "GPIO buttons init failed (pins start=%s stop=%s jog=%s rev=%s reset=%s): %s",
                self._pin_start,
                self._pin_stop,
                self._pin_jog,
                self._pin_reverse,
                self._pin_reset_wound,
                self._error,
            )
            self._start = None
            self._stop = None
            self._jog = None
            self._rev = None
            self._reset_wound = None
            return

        self._available = True
        # Seed edge detector so a button held at startup does not fire a pulse.
        self._prev_start = bool(self._start.is_pressed)
        self._prev_stop = bool(self._stop.is_pressed)
        self._prev_reset_wound = bool(self._reset_wound.is_pressed)
        log.info(
            "GPIO buttons ready via %s: start=%s stop=%s jog=%s reverse=%s reset_wound=%s "
            "(active in real and emulator modes)",
            self._pin_factory,
            self._pin_start,
            self._pin_stop,
            self._pin_jog,
            self._pin_reverse,
            self._pin_reset_wound,
        )

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str:
        return self._error

    @property
    def pin_factory(self) -> str:
        return self._pin_factory

    def _pressed(self, btn) -> bool:
        return bool(btn is not None and btn.is_pressed)

    def read_levels(self) -> GpioLevels:
        """Current pressed state of each digital input (not pulse latches)."""
        if not self._available:
            return GpioLevels(
                available=False,
                pin_start=self._pin_start,
                pin_stop=self._pin_stop,
                pin_jog=self._pin_jog,
                pin_reverse=self._pin_reverse,
                pin_reset_wound=self._pin_reset_wound,
                error=self._error,
                pin_factory=self._pin_factory,
            )
        return GpioLevels(
            available=True,
            start=self._pressed(self._start),
            stop=self._pressed(self._stop),
            jog=self._pressed(self._jog),
            reverse=self._pressed(self._rev),
            reset_wound=self._pressed(self._reset_wound),
            pin_start=self._pin_start,
            pin_stop=self._pin_stop,
            pin_jog=self._pin_jog,
            pin_reverse=self._pin_reverse,
            pin_reset_wound=self._pin_reset_wound,
            error="",
            pin_factory=self._pin_factory,
        )

    def _update_pulse_latches(self) -> None:
        """Rising-edge latch for pulse buttons (polled each control cycle)."""
        start_now = self._pressed(self._start)
        stop_now = self._pressed(self._stop)
        reset_now = self._pressed(self._reset_wound)

        if start_now and not self._prev_start:
            self._start_p.latch()
        if stop_now and not self._prev_stop:
            self._stop_p.latch()
        if reset_now and not self._prev_reset_wound:
            self._reset_wound_p.latch()

        self._prev_start = start_now
        self._prev_stop = stop_now
        self._prev_reset_wound = reset_now

    def read(self) -> Inputs:
        # estop_ok: пока нет отдельного E-STOP пина — считаем что OK
        if not self._available:
            return Inputs(
                start_pulse=self._start_p.read(),
                stop_pulse=self._stop_p.read(),
                jog_level=False,
                reverse_level=False,
                estop_ok=True,
                reset_roll_pulse=False,
                reset_wound_pulse=self._reset_wound_p.read(),
            )

        self._update_pulse_latches()
        return Inputs(
            start_pulse=self._start_p.read(),
            stop_pulse=self._stop_p.read(),
            jog_level=self._pressed(self._jog),
            reverse_level=self._pressed(self._rev),
            estop_ok=True,
            reset_roll_pulse=False,
            reset_wound_pulse=self._reset_wound_p.read(),
        )
