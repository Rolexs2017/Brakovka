from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag

from brakovka_pi.state import STATE_NAMES_RU as STATE_NAMES
from brakovka_pi.state import MOVING_STATES, RUN_LIKE_STATES, MachineState

# Re-export for HMI screens
__all__ = [
    "CmdBit",
    "StatusFlag",
    "MachineState",
    "STATE_NAMES",
    "STATE_FROM_NAME",
    "MOVING_STATES",
    "RUN_LIKE_STATES",
    "PULSE_CMD_BITS",
    "HELD_CMD_BITS",
    "MachineSnapshot",
]


class CmdBit(IntFlag):
    START = 1 << 0
    STOP = 1 << 1
    JOG = 1 << 2
    REVERSE = 1 << 3
    RESET_ROLL = 1 << 4
    RESET_WOUND = 1 << 6


class StatusFlag(IntFlag):
    RUNNING = 1 << 0
    MOVING = 1 << 1
    BRAKE = 1 << 2
    ENCODER_ERROR = 1 << 4
    MAGNET_ERROR = 1 << 5
    EMULATOR = 1 << 6
    WATCHDOG = 1 << 7
    VFD_FAULT = 1 << 8
    VFD_WARNING = 1 << 9
    MODBUS_ERROR = 1 << 10


STATE_FROM_NAME = {s.name: s for s in MachineState}

PULSE_CMD_BITS = (
    CmdBit.START | CmdBit.STOP | CmdBit.RESET_ROLL | CmdBit.RESET_WOUND
)
HELD_CMD_BITS = CmdBit.JOG | CmdBit.REVERSE


@dataclass
class MachineSnapshot:
    """Telemetry for HMI screens. Setpoints come via read_settings() / PollService."""

    connected: bool = False
    status: int = 0
    state: MachineState = MachineState.IDLE
    speed_mpm: float = 0.0
    motor_cmd_rpm: float = 0.0
    brake_pct: float = 0.0
    wound_m: float = 0.0
    diameter_mm: float = 0.0
    remaining_m: float = 0.0
    progress_pct: float = 0.0
    tension_n: float = 0.0
    vfd_freq_out_hz: float = 0.0
    # Shown on main screen; also available via settings poll.
    target_length_m: float = 0.0
    # Raw GPIO button levels (pressed = True). Pins from settings/gpio.
    gpio_available: bool = False
    gpio_start: bool = False
    gpio_stop: bool = False
    gpio_jog: bool = False
    gpio_reverse: bool = False
    gpio_reset_wound: bool = False
    gpio_pin_start: int = 23
    gpio_pin_stop: int = 24
    gpio_pin_jog: int = 25
    gpio_pin_reverse: int = 8
    gpio_pin_reset_wound: int = 7
    gpio_error: str = ""
    gpio_pin_factory: str = ""

    @property
    def state_name(self) -> str:
        try:
            return STATE_NAMES[MachineState(self.state)]
        except (ValueError, KeyError):
            return f"? ({self.state})"

    @property
    def status_flags(self) -> StatusFlag:
        return StatusFlag(self.status)
