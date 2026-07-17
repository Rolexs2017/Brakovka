from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SetpointDef:
    """Unified setpoint schema for Machine.apply_setpoint / HMI / OPC / settings.json.

    Units match apply_setpoint today (e.g. material_thickness_mm is mm, not meters).
    ``param_attr`` + ``param_scale`` convert MachineParams internal storage → external units.
    """

    key: str
    ui_key: str | None = None
    opc_name: str | None = None
    json_key: str | None = None
    lo: float = 0.0
    hi: float = float("inf")
    scale: float = 1.0
    persist: bool = False
    unit_note: str = ""
    param_attr: str | None = None
    param_scale: float = 1.0


def _sp(
    key: str,
    *,
    ui_key: str | None = None,
    opc_name: str | None = None,
    json_key: str | None = None,
    lo: float = 0.0,
    hi: float = float("inf"),
    scale: float = 1.0,
    persist: bool = False,
    unit_note: str = "",
    param_attr: str | None = None,
    param_scale: float = 1.0,
) -> SetpointDef:
    return SetpointDef(
        key=key,
        ui_key=ui_key,
        opc_name=opc_name,
        json_key=json_key if json_key is not None else (key if persist else None),
        lo=lo,
        hi=hi,
        scale=scale,
        persist=persist,
        unit_note=unit_note,
        param_attr=param_attr if param_attr is not None else key,
        param_scale=param_scale,
    )


# All Machine.apply_setpoint names + MachineConfig / HMI-related params.
_SETPOINT_LIST: tuple[SetpointDef, ...] = (
    _sp(
        "speed_setpoint_mpm",
        ui_key="speed_set_mpm",
        opc_name="SpeedSetpoint_mpm",
        lo=0.0,
        hi=300.0,
        persist=True,
        unit_note="m/min",
    ),
    _sp(
        "target_length_m",
        ui_key="target_length_m",
        opc_name="TargetLength_m",
        lo=0.0,
        hi=1e9,
        persist=True,
        unit_note="m",
    ),
    _sp(
        "jog_speed_mpm",
        ui_key="jog_speed_mpm",
        lo=0.0,
        hi=300.0,
        persist=True,
        unit_note="m/min",
    ),
    _sp(
        "reverse_speed_mpm",
        ui_key="reverse_speed_mpm",
        lo=0.0,
        hi=300.0,
        persist=True,
        unit_note="m/min",
    ),
    _sp(
        "slowdown_speed_mpm",
        ui_key="slowdown_speed_mpm",
        opc_name="SlowdownSpeed_mpm",
        lo=0.0,
        hi=300.0,
        persist=True,
        unit_note="m/min",
    ),
    _sp(
        "slowdown_start_pct",
        opc_name="SlowdownStart_pct",
        lo=1.0,
        hi=100.0,
        persist=True,
        unit_note="%",
    ),
    _sp(
        "accel_time_s",
        ui_key="accel_sec",
        opc_name="AccelTime_s",
        lo=0.1,
        hi=300.0,
        persist=True,
        unit_note="s",
    ),
    _sp(
        "decel_time_s",
        ui_key="decel_sec",
        opc_name="DecelTime_s",
        lo=0.1,
        hi=300.0,
        persist=True,
        unit_note="s",
    ),
    _sp(
        "brake_delay_s",
        ui_key="brake_delay_sec",
        lo=0.0,
        hi=60.0,
        persist=True,
        unit_note="s",
    ),
    _sp(
        "pid_kp",
        ui_key="pid_kp",
        opc_name="PidKp_HzPerMpm",
        lo=0.0,
        hi=1e6,
        persist=True,
        unit_note="Hz/(m/min)",
    ),
    _sp(
        "pid_ti",
        ui_key="pid_ti",
        opc_name="PidTi_s",
        lo=0.0,
        hi=1e6,
        persist=True,
        unit_note="s",
    ),
    _sp(
        "pid_kd",
        ui_key="pid_kd",
        opc_name="PidKd_HzSecPerMpm",
        lo=0.0,
        hi=1e6,
        persist=True,
        unit_note="Hz·s/(m/min)",
    ),
    _sp(
        "mpm_per_hz",
        ui_key="mpm_per_hz",
        lo=0.01,
        hi=1000.0,
        persist=True,
        unit_note="(m/min)/Hz feedforward gain",
    ),
    _sp(
        "roll_encoder_diameter_mm",
        ui_key="roll_diameter_mm",
        opc_name="RollEncoder_mm",
        json_key="roll_encoder_diameter_mm",
        lo=20.0,
        hi=500.0,
        persist=True,
        unit_note="mm (apply_setpoint); stored as roll_diameter_m",
        param_attr="roll_diameter_m",
        param_scale=1000.0,
    ),
    _sp(
        "emu_mpm_per_hz",
        opc_name="EmuMpmPerHz",
        lo=0.01,
        hi=1000.0,
        persist=False,
        unit_note="(m/min)/Hz emulator",
    ),
    _sp(
        "tension_setpoint_n",
        ui_key="tension_n",
        opc_name="TensionSetpoint_N",
        lo=0.0,
        hi=5000.0,
        persist=True,
        unit_note="N",
    ),
    _sp(
        "tension_brake_gain_n",
        opc_name="TensionBrakeGain_N",
        lo=1.0,
        hi=50000.0,
        persist=True,
        unit_note="N at 100% brake @ start diameter",
    ),
    _sp(
        "unwind_roll_length_m",
        ui_key="unwind_roll_length_m",
        opc_name="UnwindRollLength_m",
        lo=0.0,
        hi=1e7,
        persist=True,
        unit_note="m",
    ),
    _sp(
        "start_diameter_mm",
        ui_key="start_diameter_mm",
        lo=50.0,
        hi=3000.0,
        persist=False,
        unit_note="mm legacy SCADA; derived from length",
        param_attr="start_diameter_m",
        param_scale=1000.0,
    ),
    _sp(
        "material_thickness_mm",
        ui_key="material_thickness_mm",
        opc_name="MaterialThickness_mm",
        lo=0.001,
        hi=10.0,
        persist=True,
        unit_note="mm (apply_setpoint); stored as material_thickness_m",
        param_attr="material_thickness_m",
        param_scale=1000.0,
    ),
    _sp(
        "core_diameter_mm",
        ui_key="core_diameter_mm",
        json_key="core_diameter_mm",
        lo=10.0,
        hi=1000.0,
        persist=True,
        unit_note="mm (apply_setpoint); stored as core_diameter_m",
        param_attr="core_diameter_m",
        param_scale=1000.0,
    ),
    _sp(
        "tension_brake_min_pct",
        opc_name="TensionBrakeMin_pct",
        lo=0.0,
        hi=100.0,
        persist=True,
        unit_note="%",
    ),
    _sp(
        "brake_max_pressure_pct",
        lo=0.0,
        hi=100.0,
        persist=True,
        unit_note="%",
    ),
    _sp(
        "encoder_invert",
        ui_key="encoder_invert",
        lo=0.0,
        hi=1.0,
        persist=True,
        unit_note="0/1 invert measuring-roller direction",
    ),
)

SETPOINTS: dict[str, SetpointDef] = {s.key: s for s in _SETPOINT_LIST}

UI_TO_MACHINE: dict[str, str] = {
    s.ui_key: s.key for s in _SETPOINT_LIST if s.ui_key is not None
}

# (opc_name, machine_key, getter_hint) — getter_hint is MachineParams attr [* scale]
OPC_DEFS: list[tuple[str, str, str]] = [
    (
        s.opc_name,
        s.key,
        s.param_attr if s.param_scale == 1.0 else f"{s.param_attr}*{s.param_scale:g}",
    )
    for s in _SETPOINT_LIST
    if s.opc_name is not None
]

ROLL_SETPOINT_KEYS = ("target_length_m", "unwind_roll_length_m", "material_thickness_mm")
# Geometry that must not change while the machine is moving (HMI lock).
ROLL_GEOMETRY_KEYS = ("unwind_roll_length_m", "material_thickness_mm", "core_diameter_mm")


def clamp(key: str, value: float) -> float:
    """Clamp a value for ``key`` (apply_setpoint / UI / JSON units), applying ``scale``."""
    sp = SETPOINTS[key]
    v = float(value) * sp.scale
    if v < sp.lo:
        return sp.lo
    if v > sp.hi:
        return sp.hi
    return v


def _value_from_params(params: Any, sp: SetpointDef) -> float:
    attr = sp.param_attr or sp.key
    return float(getattr(params, attr)) * sp.param_scale


def machine_params_to_ui(params: Any) -> dict[str, float]:
    """Map MachineParams → HMI read_settings dict (ui_key → value)."""
    out: dict[str, float] = {}
    for sp in _SETPOINT_LIST:
        if sp.ui_key is None:
            continue
        out[sp.ui_key] = _value_from_params(params, sp)
    out["pid_tune_method"] = str(getattr(params, "pid_tune_method", "relay"))
    return out


def machine_params_to_json(params: Any) -> dict[str, Any]:
    """Map MachineParams → settings.json ``machine`` section (mm where needed)."""
    from .pid_tune import parse_pid_tune_method

    out: dict[str, Any] = {}
    for sp in _SETPOINT_LIST:
        if not sp.persist or sp.json_key is None:
            continue
        value = _value_from_params(params, sp)
        # Keep boolean flags as JSON bools (not 0.0/1.0).
        if sp.key == "encoder_invert":
            out[sp.json_key] = bool(value)
        else:
            out[sp.json_key] = value
    out["pid_tune_method"] = parse_pid_tune_method(getattr(params, "pid_tune_method", "relay"))
    return out
