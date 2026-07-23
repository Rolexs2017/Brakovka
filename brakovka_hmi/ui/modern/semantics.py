"""Semantic status levels for modern HMI coloring."""

from __future__ import annotations

from brakovka_hmi.snapshot import MachineSnapshot, MachineState, StatusFlag

Level = str  # ok | warn | alarm | neutral | off

ALARM_FLAGS = (
    StatusFlag.ENCODER_ERROR
    | StatusFlag.MAGNET_ERROR
    | StatusFlag.WATCHDOG
    | StatusFlag.VFD_FAULT
    | StatusFlag.MODBUS_ERROR
)

WARN_FLAGS = StatusFlag.VFD_WARNING | StatusFlag.BRAKE


def snapshot_level(snap: MachineSnapshot) -> Level:
    flags = snap.status_flags
    if flags & ALARM_FLAGS:
        return "alarm"
    if flags & WARN_FLAGS:
        return "warn"
    return machine_state_level(snap.state)


def machine_state_level(state: MachineState | int) -> Level:
    try:
        st = MachineState(state)
    except ValueError:
        return "neutral"
    if st == MachineState.RUN:
        return "ok"
    if st in (
        MachineState.JOG,
        MachineState.REVERSE,
        MachineState.SLOWDOWN,
        MachineState.STOPPING,
    ):
        return "warn"
    if st == MachineState.IDLE:
        return "ok"
    return "neutral"


def flag_chip_level(bit: StatusFlag, active: bool, *, alarm: bool) -> Level:
    if not active:
        return "off"
    if alarm:
        return "alarm"
    if bit in (StatusFlag.VFD_WARNING, StatusFlag.BRAKE, StatusFlag.EMULATOR):
        return "warn"
    return "ok"
