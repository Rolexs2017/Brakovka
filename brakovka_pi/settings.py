from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    emulator: bool
    gpio: dict[str, Any]
    serial: dict[str, Any]
    opcua: dict[str, Any]
    timing: dict[str, Any]
    vfd: dict[str, Any]
    machine: dict[str, Any]
    emu: dict[str, Any]
    ui: dict[str, Any]


def settings_path() -> Path:
    """Resolved path used by load_settings / save_machine_section."""
    pkg_dir = Path(__file__).resolve().parent
    default_path = (pkg_dir / "settings.json").resolve()
    return Path(os.getenv("BRAKOVKA_SETTINGS", str(default_path))).expanduser().resolve()


def load_settings() -> Settings:
    """
    Loads settings from JSON file.

    - Default path: brakovka_pi/settings.json (рядом с модулями пакета)
    - Override via env: BRAKOVKA_SETTINGS=/path/to/settings.json
    - Emulator env override: BRAKOVKA_EMU=1 forces emulator=true
    """
    path = settings_path()

    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if os.getenv("BRAKOVKA_EMU", "0") == "1":
        data["emulator"] = True

    for k in ("gpio", "serial", "opcua", "timing", "vfd", "machine", "emu", "ui"):
        data.setdefault(k, {})

    return Settings(
        emulator=bool(data.get("emulator", False)),
        gpio=dict(data["gpio"]),
        serial=dict(data["serial"]),
        opcua=dict(data["opcua"]),
        timing=dict(data["timing"]),
        vfd=dict(data["vfd"]),
        machine=dict(data["machine"]),
        emu=dict(data["emu"]),
        ui=dict(data["ui"]),
    )


def _read_settings_file() -> dict[str, Any]:
    path = settings_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write_settings_file(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_machine_section(machine_dict: dict) -> None:
    """Merge ``machine_dict`` into settings.json ``machine`` and write atomically."""
    data = _read_settings_file()
    machine = dict(data.get("machine") or {})
    machine.update(machine_dict)
    data["machine"] = machine
    _write_settings_file(data)


def read_emulator_setting() -> bool:
    """``emulator`` flag from settings.json (ignores BRAKOVKA_EMU / host OS)."""
    data = _read_settings_file()
    return bool(data.get("emulator", False))


def save_emulator(enabled: bool) -> None:
    """Persist top-level ``emulator`` flag; takes effect on next controller start."""
    data = _read_settings_file()
    data["emulator"] = bool(enabled)
    _write_settings_file(data)


def get_settings_password(settings: Settings | None = None) -> str:
    """Password from ``BRAKOVKA_SETTINGS_PASSWORD`` or ``settings.ui.settings_password`` (default 4444)."""
    env = os.getenv("BRAKOVKA_SETTINGS_PASSWORD")
    if env is not None:
        return env
    if settings is None:
        try:
            settings = load_settings()
        except FileNotFoundError:
            return "4444"
    return str(settings.ui.get("settings_password", "4444"))

