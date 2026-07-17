from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from math import fabs, pi
import logging
import threading
from time import monotonic

from .as5600 import AS5600_ADDR, STATUS_MD, As5600

# AS5600 raw counts per full revolution of the measuring roller.
COUNTS_PER_REV = 4096

log = logging.getLogger(__name__)


def calibrated_roll_diameter_m(true_length_m: float, pulses: int) -> float | None:
    """
    Диаметр мерного ролика по факту: L = N · π · D / 4096
    → D = L · 4096 / (π · N)
    """
    if pulses <= 0 or true_length_m <= 0.0:
        return None
    return (float(true_length_m) * float(COUNTS_PER_REV)) / (pi * float(pulses))


@dataclass
class EncoderTelemetry:
    speed_mpm: float = 0.0
    wound_m: float = 0.0
    unwind_m: float = 0.0
    pulses: int = 0
    ok: bool = True
    magnet_ok: bool = True


class SpeedMovingAverage:
    """Arithmetic mean over the last N speed samples (m/min)."""

    def __init__(self, window: int = 10) -> None:
        self._window = max(1, int(window))
        self._buf: deque[float] = deque(maxlen=self._window)
        self.value_mpm = 0.0

    def reset(self, value_mpm: float = 0.0) -> None:
        self._buf.clear()
        self.value_mpm = max(0.0, float(value_mpm))

    def update(self, raw_mpm: float) -> float:
        raw = max(0.0, float(raw_mpm))
        self._buf.append(raw)
        self.value_mpm = sum(self._buf) / len(self._buf)
        return self.value_mpm


# Fixed window before speed PID / autotune (controller).
PID_REGULATOR_SPEED_AVG_N = 10


class Encoder:
    def __init__(
        self,
        roll_diameter_m: float,
        spike_threshold_m: float = 2.0,
        max_speed_mpm: float = 300.0,
        invert: bool = False,
    ) -> None:
        self._as = As5600(bus=1, address=AS5600_ADDR)
        self._prev_raw: int | None = None
        self._unwind_pulses = 0
        self._wound_pulses = 0
        self._roll_diameter_m = roll_diameter_m
        self._spike_m = spike_threshold_m
        self._max_speed_mpm = max(1.0, float(max_speed_mpm))
        self._invert = bool(invert)
        self._last_speed_mpm = 0.0

    def set_roll_diameter_m(self, roll_diameter_m: float) -> None:
        if roll_diameter_m <= 0:
            return
        self._roll_diameter_m = roll_diameter_m

    def set_max_speed_mpm(self, max_speed_mpm: float) -> None:
        self._max_speed_mpm = max(1.0, float(max_speed_mpm))

    def set_invert(self, invert: bool) -> None:
        self._invert = bool(invert)

    def reset_unwind(self) -> None:
        """New unwind roll: consumed length = 0 (diameter = start_diameter). Keep wound."""
        self._prev_raw = None
        self._unwind_pulses = 0

    def reset_wound(self) -> None:
        """Reset consumer meterage and its pulse counter together."""
        self._wound_pulses = 0

    def close(self) -> None:
        self._as.close()

    def _meters_per_count(self) -> float:
        return (pi * self._roll_diameter_m) / float(COUNTS_PER_REV)

    def _length_m(self, pulses: int) -> float:
        return max(0.0, float(pulses) * self._meters_per_count())

    def _max_counts_per_step(self, dt_s: float) -> int:
        """Reject I2C/unwrap glitches above plausible web speed."""
        mpc = self._meters_per_count()
        if mpc <= 1e-12 or dt_s <= 0:
            return COUNTS_PER_REV
        max_m = (self._max_speed_mpm / 60.0) * dt_s * 1.5
        return max(1, int(max_m / mpc) + 1)

    def _telem(self, *, speed_mpm: float, ok: bool, magnet_ok: bool = True) -> EncoderTelemetry:
        return EncoderTelemetry(
            speed_mpm=speed_mpm,
            wound_m=self._length_m(self._wound_pulses),
            unwind_m=self._length_m(self._unwind_pulses),
            pulses=self._wound_pulses,
            ok=ok,
            magnet_ok=magnet_ok,
        )

    def step(self, dt_s: float, *, wound_enable: bool = True) -> EncoderTelemetry:
        """
        dt_s: фактический период между вызовами
        wound_enable: учитывать метраж потребителя (обычно True — ролик меряет факт)

        Метраж = накопительные импульсы × (π·D / 4096).
        Скорость — мгновенная |Δм|/dt (без сглаживания на энкодере).
        Знак импульсов — физический поворот AS5600 (см. encoder_invert).

        ok=False только при сбое чтения I2C. Отсев спайков не считается аварией
        (иначе лампа «Ошибка энкодера» мигает при каждом резком Δ).
        """
        if dt_s <= 0:
            return self._telem(speed_mpm=self._last_speed_mpm, ok=True)

        try:
            s = self._as.read()
        except Exception:
            return self._telem(
                speed_mpm=self._last_speed_mpm,
                ok=False,
                magnet_ok=False,
            )

        magnet_ok = bool(s.status & STATUS_MD)
        raw = int(s.raw) & 0x0FFF
        if self._prev_raw is None:
            self._prev_raw = raw
            self._last_speed_mpm = 0.0
            return self._telem(speed_mpm=0.0, ok=True, magnet_ok=magnet_ok)

        delta = raw - self._prev_raw
        self._prev_raw = raw

        # unwrap for 12-bit angle
        if delta > 2048:
            delta -= 4096
        elif delta < -2048:
            delta += 4096

        signed = -int(delta) if self._invert else int(delta)
        mpc = self._meters_per_count()
        delta_m = float(signed) * mpc

        # Reject I2C/unwrap glitches and overspeed samples (do not raise encoder_error).
        max_counts = self._max_counts_per_step(dt_s)
        if fabs(delta_m) > self._spike_m or abs(signed) > max_counts:
            signed = 0
            delta_m = 0.0
            speed_mpm = self._last_speed_mpm
        else:
            self._unwind_pulses = max(0, self._unwind_pulses + signed)
            if wound_enable:
                self._wound_pulses = max(0, self._wound_pulses + signed)
            speed_mpm = (fabs(delta_m) / dt_s) * 60.0
            self._last_speed_mpm = speed_mpm

        return self._telem(speed_mpm=speed_mpm, ok=True, magnet_ok=magnet_ok)


class ThreadedEncoder:
    """
    Отдельный поток: I2C AS5600 → импульсы → скорость/метраж.

    Контроллер только читает snapshot() и шлёт команды сброса/настроек.
    """

    def __init__(self, encoder: Encoder, *, period_s: float = 0.01) -> None:
        self._enc = encoder
        self._period_s = max(0.002, float(period_s))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._telem = EncoderTelemetry()
        self._wound_enable = True
        self._pending_reset_wound = False
        self._pending_reset_unwind = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="brakovka-encoder",
            daemon=True,
        )
        self._thread.start()
        log.info("Encoder thread started (period=%.3f s)", self._period_s)

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=timeout_s)
        self._thread = None

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._enc.close()

    def snapshot(self) -> EncoderTelemetry:
        with self._lock:
            return replace(self._telem)

    def set_wound_enable(self, enabled: bool) -> None:
        with self._lock:
            self._wound_enable = bool(enabled)

    def set_roll_diameter_m(self, roll_diameter_m: float) -> None:
        with self._lock:
            self._enc.set_roll_diameter_m(roll_diameter_m)

    def set_max_speed_mpm(self, max_speed_mpm: float) -> None:
        with self._lock:
            self._enc.set_max_speed_mpm(max_speed_mpm)

    def set_invert(self, invert: bool) -> None:
        with self._lock:
            self._enc.set_invert(invert)

    def reset_unwind(self) -> None:
        with self._lock:
            self._pending_reset_unwind = True

    def reset_wound(self) -> None:
        with self._lock:
            self._pending_reset_wound = True

    def _run(self) -> None:
        last_t = monotonic()
        next_t = last_t
        while not self._stop.is_set():
            now = monotonic()
            dt = now - last_t
            last_t = now
            dt = min(max(dt, 1e-4), 0.5)

            with self._lock:
                if self._pending_reset_unwind:
                    self._enc.reset_unwind()
                    self._pending_reset_unwind = False
                if self._pending_reset_wound:
                    self._enc.reset_wound()
                    self._pending_reset_wound = False
                self._telem = self._enc.step(dt, wound_enable=self._wound_enable)

            next_t += self._period_s
            sleep_s = next_t - monotonic()
            if sleep_s > 0.0:
                if self._stop.wait(sleep_s):
                    break
            else:
                # Cycle ran long (I2C stall) — resync schedule.
                next_t = monotonic()
