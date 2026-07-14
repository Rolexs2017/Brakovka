from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSnapshot:
    start: bool = False
    stop: bool = False
    jog: bool = False
    reverse: bool = False
    reset_roll: bool = False
    reset_wound: bool = False

    def as_dict(self) -> dict:
        return {
            "start": self.start,
            "stop": self.stop,
            "jog": self.jog,
            "reverse": self.reverse,
            "reset_roll": self.reset_roll,
            "reset_wound": self.reset_wound,
        }


_CMD_KEYS = ("start", "stop", "jog", "reverse", "reset_roll", "reset_wound")


def merge_command_dicts(*sources: dict) -> CommandSnapshot:
    """OR-merge command dicts (same keys as as_dict)."""
    merged = {k: False for k in _CMD_KEYS}
    for src in sources:
        if not src:
            continue
        for k in _CMD_KEYS:
            merged[k] = merged[k] or bool(src.get(k, False))
    return CommandSnapshot(**merged)
