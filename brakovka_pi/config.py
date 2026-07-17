from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

from .pid_tune import parse_pid_tune_method
from .setpoints import SETPOINTS, clamp as sp_clamp
from .settings import load_settings


def _parse_rs485_de(raw: object) -> Optional[int]:
    """null/0/negative in JSON → USB adapter (no GPIO DE)."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lower() in ("", "none", "null"):
        return None
    pin = int(raw)  # type: ignore[arg-type]
    return pin if pin > 0 else None


def _parse_pid_tune_method(raw: object) -> str:
    return parse_pid_tune_method(raw)


def resolve_emulator(emu_from_file: bool) -> bool:
    """True on non-Linux hosts, when settings/env request emulation."""
    return (
        (not sys.platform.startswith("linux"))
        or bool(emu_from_file)
        or (os.getenv("BRAKOVKA_EMU", "0") == "1")
    )


def _clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _machine_clamp(key: str, value: float, *, lo: float | None = None, hi: float | None = None) -> float:
    """Clamp using setpoints schema when available, else explicit lo/hi."""
    if key in SETPOINTS:
        return sp_clamp(key, value)
    if lo is None or hi is None:
        return float(value)
    return _clamp(float(value), lo, hi)


@dataclass(frozen=True)
class GpioConfig:
    btn_start: int = 23
    btn_stop: int = 24
    btn_jog: int = 25
    btn_reverse: int = 8
    btn_reset_wound: int = 7
    brake_pwm: int = 13


@dataclass(frozen=True)
class SerialConfig:
    port: str = "/dev/serial0"
    baudrate: int = 115200
    # Fixed 8N1 for Delta CP2000 Modbus RTU (not in settings.json).
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout_s: float = 0.5
    retries: int = 3
    unit_id: int = 1
    de_delay_before_tx_s: float = 0.002
    de_turnaround_s: float = 0.003
    # GPIO pin for software DE (SP3485 RSE). null = USB RS485 adapter (auto DE).
    rs485_de: Optional[int] = 16
    rs485_active_high: bool = True
    reconnect_period_s: float = 2.0
    fails_before_reconnect: int = 2


# Default DE/RE pin (ordinary GPIO).
RS485_DE_GPIO = 16


@dataclass(frozen=True)
class VfdConfig:
    # Delta CP2000 Modbus map (holding registers, FC 03/06) — fixed in code.
    reg_cmd: int = 0x2000
    reg_freq: int = 0x2001
    reg_status: int = 0x2000
    reg_fault: int = 0x2100
    reg_freq_out: int = 0x2103
    freq_scale: int = 100
    cmd_forward: int = 18
    cmd_reverse: int = 34
    cmd_stop: int = 1
    profile: str = "delta_cp2000"


@dataclass(frozen=True)
class OpcUaConfig:
    endpoint: str = "opc.tcp://0.0.0.0:4840/"
    server_name: str = "BrakovkaPi"


@dataclass(frozen=True)
class MachineConfig:
    unwind_roll_length_m: float = 2500.0
    core_diameter_mm: float = 76.0
    material_thickness_mm: float = 0.3
    roll_encoder_diameter_mm: float = 200.0
    tension_setpoint_n: float = 150.0
    tension_brake_gain_n: float = 500.0
    target_length_m: float = 500.0
    speed_setpoint_mpm: float = 100.0
    slowdown_speed_mpm: float = 20.0
    slowdown_start_pct: float = 90.0
    accel_time_s: float = 15.0
    decel_time_s: float = 10.0
    jog_speed_mpm: float = 10.0
    reverse_speed_mpm: float = 15.0
    brake_delay_s: float = 3.0
    pid_kp: float = 5.0
    pid_ti: float = 2.0
    pid_kd: float = 0.0
    pid_tune_method: str = "relay"
    mpm_per_hz: float = 1.0
    tension_brake_min_pct: float = 2.0
    brake_max_pressure_pct: float = 100.0
    max_ramp_speed_mpm: float = 300.0
    encoder_spike_m: float = 2.0
    encoder_speed_filter_n: int = 5
    vfd_cmd_filter_tau_s: float = 0.0
    encoder_invert: bool = False
    emu_mpm_per_hz: float = 1.0
    emu_motor_rpm_per_hz: float = 60.0

    def apply_to(self, machine) -> None:
        p = machine.params
        p.unwind_roll_length_m = self.unwind_roll_length_m
        p.core_diameter_m = self.core_diameter_mm / 1000.0
        p.material_thickness_m = self.material_thickness_mm / 1000.0
        p.roll_diameter_m = self.roll_encoder_diameter_mm / 1000.0
        p.tension_setpoint_n = self.tension_setpoint_n
        p.tension_brake_gain_n = self.tension_brake_gain_n
        p.target_length_m = self.target_length_m
        p.speed_setpoint_mpm = self.speed_setpoint_mpm
        p.slowdown_speed_mpm = self.slowdown_speed_mpm
        p.slowdown_start_pct = self.slowdown_start_pct
        p.accel_time_s = self.accel_time_s
        p.decel_time_s = self.decel_time_s
        p.jog_speed_mpm = self.jog_speed_mpm
        p.reverse_speed_mpm = self.reverse_speed_mpm
        p.brake_delay_s = self.brake_delay_s
        p.pid_kp = self.pid_kp
        p.pid_ti = self.pid_ti
        p.pid_kd = self.pid_kd
        p.pid_tune_method = parse_pid_tune_method(self.pid_tune_method)
        p.mpm_per_hz = self.mpm_per_hz
        p.tension_brake_min_pct = self.tension_brake_min_pct
        p.brake_max_pressure_pct = self.brake_max_pressure_pct
        p.max_ramp_speed_mpm = self.max_ramp_speed_mpm
        p.encoder_spike_m = self.encoder_spike_m
        p.encoder_speed_filter_n = self.encoder_speed_filter_n
        p.vfd_cmd_filter_tau_s = self.vfd_cmd_filter_tau_s
        p.encoder_invert = self.encoder_invert
        p.emu_mpm_per_hz = self.emu_mpm_per_hz
        p.emu_motor_rpm_per_hz = self.emu_motor_rpm_per_hz
        machine.sync_start_diameter_from_roll_length()
        machine.telem.unwind_diameter_mm = machine.params.start_diameter_m * 1000.0


@dataclass(frozen=True)
class TimingConfig:
    task_period_s: float = 0.01
    opcua_publish_period_s: float = 0.1
    opcua_poll_period_s: float = 0.05
    vfd_status_poll_period_s: float = 0.2
    vfd_cmd_period_s: float = 0.05
    vfd_cmd_min_delta_hz: float = 0.05
    # Absolute stall limit (not 5×task_period). Must exceed Modbus timeout×retries.
    watchdog_limit_s: float = 5.0


def load_runtime_config():
    s = load_settings()

    gpio = GpioConfig(
        btn_start=int(s.gpio.get("btn_start", 23)),
        btn_stop=int(s.gpio.get("btn_stop", 24)),
        btn_jog=int(s.gpio.get("btn_jog", 25)),
        btn_reverse=int(s.gpio.get("btn_reverse", 8)),
        btn_reset_wound=int(s.gpio.get("btn_reset_wound", 7)),
        brake_pwm=int(s.gpio.get("brake_pwm", 13)),
    )

    serial = SerialConfig(
        port=str(s.serial.get("port", "/dev/serial0")),
        baudrate=int(s.serial.get("baudrate", 115200)),
        timeout_s=float(s.serial.get("timeout_s", 0.5)),
        retries=int(s.serial.get("retries", 3)),
        unit_id=int(s.serial.get("unit_id", 1)),
        de_delay_before_tx_s=float(s.serial.get("de_delay_before_tx_s", 0.002)),
        de_turnaround_s=float(s.serial.get("de_turnaround_s", 0.003)),
        rs485_de=_parse_rs485_de(s.serial.get("rs485_de", 16)),
        rs485_active_high=bool(s.serial.get("rs485_active_high", True)),
        reconnect_period_s=_clamp(float(s.serial.get("reconnect_period_s", 2.0)), 0.5, 60.0),
        fails_before_reconnect=max(1, int(s.serial.get("fails_before_reconnect", 2))),
    )

    # Delta CP2000 register map is fixed in VfdConfig defaults (not in settings.json).
    vfd = VfdConfig()

    opcua = OpcUaConfig(
        endpoint=str(s.opcua.get("endpoint", "opc.tcp://0.0.0.0:4840/")),
        server_name=str(s.opcua.get("server_name", "BrakovkaPi")),
    )

    timing = TimingConfig(
        task_period_s=_clamp(float(s.timing.get("task_period_s", 0.01)), 0.002, 1.0),
        opcua_publish_period_s=_clamp(float(s.timing.get("opcua_publish_period_s", 0.1)), 0.02, 10.0),
        opcua_poll_period_s=_clamp(float(s.timing.get("opcua_poll_period_s", 0.05)), 0.02, 10.0),
        vfd_status_poll_period_s=_clamp(float(s.timing.get("vfd_status_poll_period_s", 0.2)), 0.05, 10.0),
        vfd_cmd_period_s=_clamp(float(s.timing.get("vfd_cmd_period_s", 0.05)), 0.01, 10.0),
        vfd_cmd_min_delta_hz=_clamp(float(s.timing.get("vfd_cmd_min_delta_hz", 0.05)), 0.0, 50.0),
        watchdog_limit_s=_clamp(float(s.timing.get("watchdog_limit_s", 5.0)), 0.5, 60.0),
    )

    machine_raw = s.machine
    core_mm = _machine_clamp("core_diameter_mm", float(machine_raw.get("core_diameter_mm", 76.0)))
    thickness_mm = _machine_clamp(
        "material_thickness_mm", float(machine_raw.get("material_thickness_mm", 0.3))
    )
    if "unwind_roll_length_m" in machine_raw:
        unwind_len = _machine_clamp(
            "unwind_roll_length_m", float(machine_raw["unwind_roll_length_m"])
        )
    elif "start_diameter_mm" in machine_raw:
        # Migrate legacy diameter setpoint → length.
        from .roll_geometry import remaining_length_m

        d_m = _machine_clamp("start_diameter_mm", float(machine_raw["start_diameter_mm"])) / 1000.0
        unwind_len = remaining_length_m(d_m, core_mm / 1000.0, thickness_mm / 1000.0)
    else:
        unwind_len = 2500.0

    machine = MachineConfig(
        unwind_roll_length_m=unwind_len,
        core_diameter_mm=core_mm,
        material_thickness_mm=thickness_mm,
        roll_encoder_diameter_mm=_machine_clamp(
            "roll_encoder_diameter_mm",
            float(machine_raw.get("roll_encoder_diameter_mm", 200.0)),
        ),
        tension_setpoint_n=_machine_clamp(
            "tension_setpoint_n", float(machine_raw.get("tension_setpoint_n", 150.0))
        ),
        tension_brake_gain_n=_machine_clamp(
            "tension_brake_gain_n", float(machine_raw.get("tension_brake_gain_n", 500.0))
        ),
        target_length_m=_machine_clamp(
            "target_length_m", float(machine_raw.get("target_length_m", 500.0))
        ),
        speed_setpoint_mpm=_machine_clamp(
            "speed_setpoint_mpm", float(machine_raw.get("speed_setpoint_mpm", 100.0))
        ),
        slowdown_speed_mpm=_machine_clamp(
            "slowdown_speed_mpm", float(machine_raw.get("slowdown_speed_mpm", 20.0))
        ),
        slowdown_start_pct=_machine_clamp(
            "slowdown_start_pct", float(machine_raw.get("slowdown_start_pct", 90.0))
        ),
        accel_time_s=_machine_clamp(
            "accel_time_s", float(machine_raw.get("accel_time_s", 15.0))
        ),
        decel_time_s=_machine_clamp(
            "decel_time_s", float(machine_raw.get("decel_time_s", 10.0))
        ),
        jog_speed_mpm=_machine_clamp(
            "jog_speed_mpm", float(machine_raw.get("jog_speed_mpm", 10.0))
        ),
        reverse_speed_mpm=_machine_clamp(
            "reverse_speed_mpm", float(machine_raw.get("reverse_speed_mpm", 15.0))
        ),
        brake_delay_s=_machine_clamp(
            "brake_delay_s", float(machine_raw.get("brake_delay_s", 3.0))
        ),
        pid_kp=_machine_clamp("pid_kp", float(machine_raw.get("pid_kp", 5.0))),
        pid_ti=_machine_clamp("pid_ti", float(machine_raw.get("pid_ti", 2.0))),
        pid_kd=_machine_clamp("pid_kd", float(machine_raw.get("pid_kd", 0.0))),
        pid_tune_method=_parse_pid_tune_method(machine_raw.get("pid_tune_method", "relay")),
        mpm_per_hz=_machine_clamp("mpm_per_hz", float(machine_raw.get("mpm_per_hz", 1.0))),
        tension_brake_min_pct=_machine_clamp(
            "tension_brake_min_pct", float(machine_raw.get("tension_brake_min_pct", 2.0))
        ),
        brake_max_pressure_pct=_machine_clamp(
            "brake_max_pressure_pct", float(machine_raw.get("brake_max_pressure_pct", 100.0))
        ),
        max_ramp_speed_mpm=_machine_clamp(
            "max_ramp_speed_mpm",
            float(machine_raw.get("max_ramp_speed_mpm", 300.0)),
            lo=0.0,
            hi=1000.0,
        ),
        encoder_spike_m=_machine_clamp(
            "encoder_spike_m",
            float(machine_raw.get("encoder_spike_m", 2.0)),
            lo=0.01,
            hi=100.0,
        ),
        encoder_speed_filter_n=max(
            1, int(machine_raw.get("encoder_speed_filter_n", 5))
        ),
        vfd_cmd_filter_tau_s=_machine_clamp(
            "vfd_cmd_filter_tau_s",
            float(machine_raw.get("vfd_cmd_filter_tau_s", 0.0)),
            lo=0.0,
            hi=10.0,
        ),
        encoder_invert=bool(machine_raw.get("encoder_invert", False)),
        emu_mpm_per_hz=_machine_clamp(
            "emu_mpm_per_hz", float(machine_raw.get("emu_mpm_per_hz", 1.0))
        ),
        emu_motor_rpm_per_hz=_machine_clamp(
            "emu_motor_rpm_per_hz",
            float(machine_raw.get("emu_motor_rpm_per_hz", 60.0)),
            lo=0.01,
            hi=10000.0,
        ),
    )

    emu = dict(s.emu)
    return s.emulator, gpio, serial, vfd, opcua, timing, machine, emu
