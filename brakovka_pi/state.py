from enum import IntEnum


class MachineState(IntEnum):
    IDLE = 0
    RUN = 1
    JOG = 2
    REVERSE = 3
    SLOWDOWN = 4
    STOPPING = 5


STATE_NAMES_RU = {
    MachineState.IDLE: "ОЖИДАНИЕ",
    MachineState.RUN: "РАБОТА",
    MachineState.JOG: "ТОЛЧОК",
    MachineState.REVERSE: "РЕВЕРС",
    MachineState.SLOWDOWN: "ЗАМЕДЛЕНИЕ",
    MachineState.STOPPING: "ОСТАНОВ",
}

MOVING_STATES = frozenset({MachineState.RUN, MachineState.JOG, MachineState.REVERSE, MachineState.SLOWDOWN})
RUN_LIKE_STATES = frozenset({MachineState.RUN, MachineState.SLOWDOWN})
