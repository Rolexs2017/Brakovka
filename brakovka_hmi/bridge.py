from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from brakovka_hmi.snapshot import (
    CmdBit,
    HELD_CMD_BITS,
    MachineSnapshot,
    MachineState,
    PULSE_CMD_BITS,
    STATE_FROM_NAME,
    StatusFlag,
)
from brakovka_pi.commands import CommandSnapshot
from brakovka_pi.setpoints import (
    ROLL_GEOMETRY_KEYS,
    UI_TO_MACHINE,
    machine_params_to_json,
    machine_params_to_ui,
)
from brakovka_pi.gpio_io import GpioLevels
from brakovka_pi.settings import (
    read_emulator_setting,
    save_emulator,
    save_machine_section,
)
from brakovka_pi.state import MOVING_STATES, RUN_LIKE_STATES

if TYPE_CHECKING:
    from brakovka_pi.machine import Machine

log = logging.getLogger(__name__)


class LocalBridge:
    """Thread-safe in-process link between Qt HMI and Machine controller."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._machine: Machine | None = None
        self._emulator = False
        self._running = False
        self._held_bits = 0
        self._pulse_bits = 0
        # Set after HMI Save / Reset roll — controller syncs OPC Setpoints from Machine.
        self._opc_sync_pending = False
        self._gpio_levels = GpioLevels()

    def attach(
        self,
        machine: Machine,
        *,
        emulator: bool = False,
        ready_event: threading.Event | None = None,
    ) -> None:
        with self._lock:
            self._machine = machine
            self._emulator = emulator
            self._running = True
        if ready_event is not None:
            ready_event.set()

    def detach(self) -> None:
        with self._lock:
            self._running = False
            self._machine = None
            self._held_bits = 0
            self._pulse_bits = 0

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def pulse_command(self, bit: CmdBit) -> bool:
        if bit not in PULSE_CMD_BITS:
            return False
        with self._lock:
            if not self._running:
                return False
            self._pulse_bits |= int(bit)
            return True

    def set_held_command(self, bit: CmdBit, active: bool) -> bool:
        if bit not in HELD_CMD_BITS:
            return False
        with self._lock:
            if not self._running:
                return False
            if active:
                self._held_bits |= int(bit)
            else:
                self._held_bits &= ~int(bit)
            return True

    def release_all_held(self) -> bool:
        with self._lock:
            self._held_bits &= ~int(HELD_CMD_BITS)
            return True

    def snapshot_inputs(self) -> dict:
        """Consume pulse latches; return levels for merge with GPIO/OPC."""
        with self._lock:
            pulses = self._pulse_bits
            held = self._held_bits
            self._pulse_bits = 0
            return CommandSnapshot(
                start=bool(pulses & int(CmdBit.START)),
                stop=bool(pulses & int(CmdBit.STOP)),
                jog=bool(held & int(CmdBit.JOG)),
                reverse=bool(held & int(CmdBit.REVERSE)),
                reset_roll=bool(pulses & int(CmdBit.RESET_ROLL)),
                reset_wound=bool(pulses & int(CmdBit.RESET_WOUND)),
            ).as_dict()

    def motion_active(self) -> bool:
        with self._lock:
            if self._machine is None:
                return False
            return self._machine.is_motion_active()

    def write_settings(self, values: dict[str, float]) -> bool:
        """Apply setpoints from HMI only when operator presses Save / Reset roll."""
        with self._lock:
            if self._machine is None:
                return False
            allow_roll = self._machine.allow_roll_edit()
            applied = False
            blocked_roll = False
            for key, value in values.items():
                sp = UI_TO_MACHINE.get(key)
                if sp is None:
                    continue
                if sp in ROLL_GEOMETRY_KEYS and not allow_roll:
                    blocked_roll = True
                    continue
                self._machine.apply_setpoint(sp, float(value))
                applied = True

            if blocked_roll and not applied:
                return False

            if applied:
                try:
                    save_machine_section(machine_params_to_json(self._machine.params))
                except Exception:
                    log.exception("Failed to persist machine section to settings.json")
                self._opc_sync_pending = True
            return True

    def take_opc_sync_pending(self) -> bool:
        """Consume flag: HMI changed Machine params and OPC nodes need refresh."""
        with self._lock:
            pending = self._opc_sync_pending
            self._opc_sync_pending = False
            return pending

    def publish_gpio_levels(self, levels: GpioLevels) -> None:
        """Controller publishes raw digital input levels for Status screen."""
        with self._lock:
            self._gpio_levels = levels

    def is_emulator_active(self) -> bool:
        """True if the running controller uses emulation (VFD/encoder)."""
        with self._lock:
            return bool(self._emulator)

    def read_emulator_setting(self) -> bool:
        """Configured ``emulator`` from settings.json (next start)."""
        return read_emulator_setting()

    def write_emulator_setting(self, enabled: bool) -> bool:
        """Save ``emulator`` to settings.json. Needs app restart to apply."""
        try:
            save_emulator(bool(enabled))
            return True
        except Exception:
            log.exception("Failed to persist emulator flag to settings.json")
            return False

    def read_settings(self) -> dict[str, float] | None:
        with self._lock:
            m = self._machine
            if m is None:
                return None
            return machine_params_to_ui(m.params)

    def read_snapshot(self) -> MachineSnapshot:
        with self._lock:
            m = self._machine
            if m is None or not self._running:
                return MachineSnapshot(connected=False)

            t = m.telem
            p = m.params
            state = STATE_FROM_NAME.get(t.state.name, MachineState.IDLE)
            moving = state in MOVING_STATES
            status = 0
            if state in RUN_LIKE_STATES:
                status |= int(StatusFlag.RUNNING)
            if moving:
                status |= int(StatusFlag.MOVING)
            if t.brake_pressure_pct > 0.5:
                status |= int(StatusFlag.BRAKE)
            if t.encoder_error:
                status |= int(StatusFlag.ENCODER_ERROR)
            if not t.magnet_ok:
                status |= int(StatusFlag.MAGNET_ERROR)
            if self._emulator:
                status |= int(StatusFlag.EMULATOR)
            if t.watchdog_fault:
                status |= int(StatusFlag.WATCHDOG)
            if t.vfd_fault:
                status |= int(StatusFlag.VFD_FAULT)
            if t.vfd_warning:
                status |= int(StatusFlag.VFD_WARNING)
            if t.modbus_error:
                status |= int(StatusFlag.MODBUS_ERROR)

            motor_rpm = float(t.vfd_freq_cmd_hz) * float(p.emu_motor_rpm_per_hz)
            g = self._gpio_levels
            return MachineSnapshot(
                connected=True,
                status=status,
                state=state,
                speed_mpm=float(t.speed_mpm),
                motor_cmd_rpm=motor_rpm,
                brake_pct=float(t.brake_pressure_pct),
                wound_m=float(t.wound_length_m),
                diameter_mm=float(t.unwind_diameter_mm),
                remaining_m=float(m.remaining_length_m()),
                progress_pct=float(t.wound_progress_pct),
                tension_n=float(t.tension_n),
                vfd_freq_out_hz=float(t.vfd_freq_out_hz),
                target_length_m=float(p.target_length_m),
                gpio_available=bool(g.available),
                gpio_start=bool(g.start),
                gpio_stop=bool(g.stop),
                gpio_jog=bool(g.jog),
                gpio_reverse=bool(g.reverse),
                gpio_reset_wound=bool(g.reset_wound),
                gpio_pin_start=int(g.pin_start),
                gpio_pin_stop=int(g.pin_stop),
                gpio_pin_jog=int(g.pin_jog),
                gpio_pin_reverse=int(g.pin_reverse),
                gpio_pin_reset_wound=int(g.pin_reset_wound),
                gpio_error=str(g.error or ""),
                gpio_pin_factory=str(g.pin_factory or ""),
            )
