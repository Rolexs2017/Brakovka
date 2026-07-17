from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from time import monotonic

from .pid import Pid
from .pid_tune import PidTuneMethod, parse_pid_tune_method
from .roll_geometry import remaining_length_m as _length_from_diameter_m
from .roll_geometry import start_diameter_from_length_m
from .roll_geometry import unwind_diameter_m as _unwind_diameter_m
from .setpoints import SETPOINTS, clamp
from .state import MOVING_STATES, MachineState


@dataclass
class MachineParams:
    # Roll geometry (meters)
    # Operator sets loaded unwind length; start_diameter_m is derived from it.
    unwind_roll_length_m: float = 2500.0
    start_diameter_m: float = 0.8
    core_diameter_m: float = 0.076
    material_thickness_m: float = 0.0003
    roll_diameter_m: float = 0.2  # measuring roller (RollEncoder)

    # Ramp / motion setpoints (m/min)
    accel_time_s: float = 15.0
    decel_time_s: float = 10.0
    max_ramp_speed_mpm: float = 300.0

    tension_setpoint_n: float = 150.0
    tension_brake_gain_n: float = 500.0  # N at 100% brake when D = start_diameter_m
    tension_brake_min_pct: float = 2.0
    speed_setpoint_mpm: float = 100.0
    target_length_m: float = 500.0
    jog_speed_mpm: float = 10.0
    reverse_speed_mpm: float = 15.0
    slowdown_speed_mpm: float = 20.0
    slowdown_start_pct: float = 90.0

    brake_delay_s: float = 3.0
    brake_max_pressure_pct: float = 100.0

    encoder_spike_m: float = 2.0
    encoder_invert: bool = False

    pid_kp: float = 5.0
    pid_ti: float = 2.0
    pid_kd: float = 0.0
    # relay | step_imc | pi_ff — autotune method and runtime control strategy
    pid_tune_method: str = "relay"
    # Feedforward gain (m/min)/Hz for pi_ff mode on real hardware
    mpm_per_hz: float = 1.0

    # Emulator only: mapping Hz -> m/min
    emu_mpm_per_hz: float = 1.0
    emu_motor_rpm_per_hz: float = 60.0


@dataclass
class Inputs:
    start_pulse: bool = False
    stop_pulse: bool = False
    jog_level: bool = False
    reverse_level: bool = False
    estop_ok: bool = True
    reset_roll_pulse: bool = False
    reset_wound_pulse: bool = False


@dataclass
class Telemetry:
    speed_mpm: float = 0.0
    wound_length_m: float = 0.0
    unwind_length_m: float = 0.0
    vfd_freq_cmd_hz: float = 0.0
    vfd_freq_out_hz: float = 0.0
    brake_pressure_pct: float = 0.0
    tension_n: float = 0.0
    unwind_diameter_mm: float = 0.0
    encoder_error: bool = False
    magnet_ok: bool = True
    encoder_pulses: int = 0
    watchdog_fault: bool = False
    vfd_status_word: int = 0
    vfd_error_code: int = 0
    vfd_fault: bool = False
    vfd_warning: bool = False
    modbus_error: bool = False
    emu_consumer_diameter_mm: float = 0.0
    ramp_speed_mpm: float = 0.0
    wound_progress_pct: float = 0.0
    state: MachineState = MachineState.IDLE
    autotune_active: bool = False
    autotune_status: str = "idle"  # idle|running|ok|fail|aborted
    autotune_message: str = ""


@dataclass
class Machine:
    params: MachineParams = field(default_factory=MachineParams)
    telem: Telemetry = field(default_factory=Telemetry)

    brake_until_t: float = 0.0
    _ramp_speed_mpm: float = 0.0
    _pid_speed: Pid = field(default_factory=lambda: Pid(kp=5.0, ti=2.0, kd=0.0, out_min=0.0, out_max=320.0))

    def is_motion_active(self) -> bool:
        return self.telem.state in MOVING_STATES

    def allow_roll_edit(self) -> bool:
        return self.telem.state == MachineState.IDLE and not self.telem.autotune_active

    def wound_progress_pct(self) -> float:
        target = self.params.target_length_m
        if target <= 1e-6:
            return 0.0
        return max(0.0, min(100.0, (self.telem.wound_length_m / target) * 100.0))

    def should_enter_slowdown(self) -> bool:
        if self.params.target_length_m <= 1e-6:
            return False
        return self.wound_progress_pct() >= self.params.slowdown_start_pct

    def should_stop_at_target_length(self) -> bool:
        if self.params.target_length_m <= 1e-6:
            return False
        return self.telem.wound_length_m >= self.params.target_length_m

    def _enter_stopping(self) -> None:
        """Cut motor immediately and hold brake 100% for brake_delay_s (wall clock)."""
        self.telem.state = MachineState.STOPPING
        self.brake_until_t = monotonic() + max(0.0, float(self.params.brake_delay_s))
        self._ramp_speed_mpm = 0.0
        self.telem.ramp_speed_mpm = 0.0
        self.reset_pid()

    def fault_stop(self, reason: str = "") -> bool:
        """Stop motion on fault. Returns True if STOPPING was entered."""
        if self.telem.autotune_active:
            self.abort_autotune(reason or "Авария")
        if self.telem.state in (MachineState.IDLE, MachineState.STOPPING):
            return False
        self._enter_stopping()
        _ = reason
        return True

    def start_autotune(self) -> bool:
        """Request PID autotune test run. Only from IDLE without faults."""
        if self.telem.state != MachineState.IDLE:
            return False
        if self.telem.autotune_active:
            return False
        if self.telem.vfd_fault or self.telem.modbus_error or self.telem.encoder_error:
            return False
        if self.telem.watchdog_fault:
            return False
        self.telem.autotune_active = True
        self.telem.autotune_status = "running"
        self.telem.autotune_message = "Запуск…"
        # Hold RUN-like motion while autotune drives VFD (no START pulse needed).
        self.telem.state = MachineState.RUN
        self._ramp_speed_mpm = 0.0
        self.telem.ramp_speed_mpm = 0.0
        self.reset_pid()
        return True

    def abort_autotune(self, reason: str = "Прервано") -> None:
        if not self.telem.autotune_active and self.telem.autotune_status != "running":
            return
        self.telem.autotune_active = False
        self.telem.autotune_status = "aborted"
        self.telem.autotune_message = reason
        if self.telem.state not in (MachineState.IDLE, MachineState.STOPPING):
            self._enter_stopping()

    def finish_autotune_ok(self, message: str) -> None:
        self.telem.autotune_active = False
        self.telem.autotune_status = "ok"
        self.telem.autotune_message = message
        if self.telem.state not in (MachineState.IDLE, MachineState.STOPPING):
            self._enter_stopping()

    def finish_autotune_fail(self, message: str) -> None:
        self.telem.autotune_active = False
        self.telem.autotune_status = "fail"
        self.telem.autotune_message = message
        if self.telem.state not in (MachineState.IDLE, MachineState.STOPPING):
            self._enter_stopping()

    def update_state(self, inp: Inputs) -> None:
        self.telem.wound_progress_pct = self.wound_progress_pct()
        st = self.telem.state
        fault_block = self.telem.vfd_fault or self.telem.modbus_error

        if self.telem.autotune_active:
            # Only STOP / estop / fault end the test; ignore START/JOG/REVERSE.
            if inp.stop_pulse or (not inp.estop_ok) or fault_block:
                self.abort_autotune(
                    "СТОП" if inp.stop_pulse else ("E-STOP" if not inp.estop_ok else "Авария")
                )
            return

        if st == MachineState.IDLE:
            if (
                inp.start_pulse
                and inp.estop_ok
                and not inp.stop_pulse
                and not inp.jog_level
                and not inp.reverse_level
                and not fault_block
            ):
                self.telem.state = MachineState.RUN
                self._ramp_speed_mpm = 0.0
            elif inp.jog_level and inp.estop_ok and not fault_block:
                self.telem.state = MachineState.JOG
            elif inp.reverse_level and inp.estop_ok and not fault_block:
                self.telem.state = MachineState.REVERSE
        elif st == MachineState.RUN:
            stop_request = (
                inp.stop_pulse
                or (not inp.estop_ok)
                or self.should_stop_at_target_length()
                or fault_block
            )
            if stop_request:
                self._enter_stopping()
            elif self.should_enter_slowdown():
                self.telem.state = MachineState.SLOWDOWN
        elif st == MachineState.SLOWDOWN:
            stop_request = (
                inp.stop_pulse
                or (not inp.estop_ok)
                or self.should_stop_at_target_length()
                or fault_block
            )
            if stop_request:
                self._enter_stopping()
            elif not self.should_enter_slowdown():
                self.telem.state = MachineState.RUN
        elif st == MachineState.JOG:
            if (not inp.jog_level) or fault_block:
                self._enter_stopping()
        elif st == MachineState.REVERSE:
            if (not inp.reverse_level) or fault_block:
                self._enter_stopping()
        elif st == MachineState.STOPPING:
            self._ramp_speed_mpm = 0.0
            self.telem.ramp_speed_mpm = 0.0
            if monotonic() >= self.brake_until_t:
                self.telem.state = MachineState.IDLE
                self.brake_until_t = 0.0

    def desired_speed_mpm(self) -> float:
        st = self.telem.state
        if st == MachineState.RUN:
            return self.params.speed_setpoint_mpm
        if st == MachineState.SLOWDOWN:
            return self.params.slowdown_speed_mpm
        if st == MachineState.JOG:
            return self.params.jog_speed_mpm
        if st == MachineState.REVERSE:
            return self.params.reverse_speed_mpm
        return 0.0

    def update_speed_ramp(self, dt_s: float) -> float:
        """Плавный разгон/торможение к уставке. STOPPING — мгновенный сброс в 0."""
        if dt_s <= 0:
            return self._ramp_speed_mpm

        # STOP / STOPPING: no software deceleration — cut speed immediately.
        if self.telem.state in (MachineState.IDLE, MachineState.STOPPING):
            self._ramp_speed_mpm = 0.0
            self.telem.ramp_speed_mpm = 0.0
            return 0.0

        target = min(self.desired_speed_mpm(), self.params.max_ramp_speed_mpm)
        current = self._ramp_speed_mpm

        if target > current + 1e-6:
            rate = self.params.speed_setpoint_mpm / max(self.params.accel_time_s, 1e-6)
            current = min(target, current + rate * dt_s)
        elif target < current - 1e-6:
            rate = self.params.speed_setpoint_mpm / max(self.params.decel_time_s, 1e-6)
            current = max(target, current - rate * dt_s)
        else:
            current = target

        self._ramp_speed_mpm = current
        self.telem.ramp_speed_mpm = current
        return current

    def tension_control_enabled(self) -> bool:
        return self.telem.state in (MachineState.RUN, MachineState.SLOWDOWN, MachineState.JOG)

    def sync_start_diameter_from_roll_length(self) -> None:
        """Derive initial unwind diameter from loaded meterage + thickness + core."""
        self.params.start_diameter_m = start_diameter_from_length_m(
            self.params.core_diameter_m,
            self.params.material_thickness_m,
            self.params.unwind_roll_length_m,
        )

    def unwind_diameter_m(self) -> float:
        """Estimate remaining diameter of the unwinding roll from consumed length."""
        return _unwind_diameter_m(
            self.params.start_diameter_m,
            self.params.core_diameter_m,
            self.params.material_thickness_m,
            self.telem.unwind_length_m,
        )

    def remaining_length_m(self) -> float:
        """Remaining material on the unwind roll (set length minus consumed)."""
        return max(0.0, self.params.unwind_roll_length_m - self.telem.unwind_length_m)

    def apply_new_unwind_roll(self) -> None:
        """
        «Сброс рулона»: потреблённая длина = 0, диаметр = расчётный от метража,
        остаток = заданный метраж рулона. Намотку потребителя не трогаем.
        """
        self.sync_start_diameter_from_roll_length()
        self.telem.unwind_length_m = 0.0
        d0 = max(self.params.core_diameter_m, self.params.start_diameter_m)
        self.telem.unwind_diameter_mm = d0 * 1000.0

    def calc_tension_n(self, brake_pct: float) -> float:
        """
        Натяжение без датчика — жёсткая геометрия (железо и эмуляция одинаково):

        T = (brake_pct / 100) * gain * (D0 / D)
        """
        d = self.unwind_diameter_m()
        d0 = max(self.params.core_diameter_m, self.params.start_diameter_m)
        ratio = d0 / max(d, self.params.core_diameter_m)
        gain = self.params.tension_brake_gain_n
        return max(0.0, (max(0.0, brake_pct) / 100.0) * gain * ratio)

    def tension_feedforward_pct(self, setpoint_n: float) -> float:
        """PWM для заданного натяжения при текущем диаметре (без PID)."""
        d = self.unwind_diameter_m()
        d0 = max(self.params.core_diameter_m, self.params.start_diameter_m)
        denom = self.params.tension_brake_gain_n * (d0 / max(d, self.params.core_diameter_m))
        if denom <= 1e-6:
            return self.params.tension_brake_min_pct
        return (setpoint_n / denom) * 100.0

    def tension_brake_command_pct(self) -> float:
        """Только feedforward от уставки и диаметра."""
        out = self.tension_feedforward_pct(self.params.tension_setpoint_n)
        out_min = self.params.tension_brake_min_pct
        out_max = self.params.brake_max_pressure_pct
        if out < out_min:
            return out_min
        if out > out_max:
            return out_max
        return float(out)

    def brake_pressure_pct(self, tension_brake_pct: float) -> float:
        """Feedforward brake + stop/hold logic."""
        if self.telem.state == MachineState.STOPPING:
            return self.params.brake_max_pressure_pct
        if not self.tension_control_enabled():
            return 0.0
        return max(0.0, min(self.params.brake_max_pressure_pct, tension_brake_pct))

    def uses_pi_feedforward(self) -> bool:
        return parse_pid_tune_method(self.params.pid_tune_method) == PidTuneMethod.PI_FF.value

    def effective_mpm_per_hz(self) -> float:
        if self.uses_pi_feedforward():
            return max(0.01, float(self.params.mpm_per_hz))
        return max(0.01, float(self.params.emu_mpm_per_hz))

    def pid_speed_to_hz(self, setpoint_mpm: float, actual_mpm: float, dt_s: float) -> float:
        """
        PID: ошибка в м/мин, выход в Гц (непосредственно задаём ПЧВ‑3 через 0x3100).

        Коэффициенты:
        - pid_kp: Гц / (м/мин)
        - pid_ti: сек (интегральное время), 0 отключает I‑составляющую
        - pid_kd: Гц * сек / (м/мин)
        """
        # Avoid integral windup at idle: when setpoint is ~0, stop integrating.
        if setpoint_mpm <= 0.01:
            self._pid_speed.reset()
            return 0.0

        err = setpoint_mpm - actual_mpm
        self._pid_speed.kp = self.params.pid_kp
        self._pid_speed.ti = self.params.pid_ti
        self._pid_speed.kd = self.params.pid_kd
        self._pid_speed.out_min = 0.0
        self._pid_speed.out_max = 320.0
        return self._pid_speed.step(err, dt_s)

    def pid_speed_to_hz_ff(self, setpoint_mpm: float, actual_mpm: float, dt_s: float) -> float:
        """
        PI + feedforward: freq = setpoint/mpm_per_hz + PI(error).

        Kd is forced to 0 (PI correction only).
        """
        if setpoint_mpm <= 0.01:
            self._pid_speed.reset()
            return 0.0

        ff_hz = setpoint_mpm / self.effective_mpm_per_hz()
        err = setpoint_mpm - actual_mpm
        self._pid_speed.kp = self.params.pid_kp
        self._pid_speed.ti = self.params.pid_ti
        self._pid_speed.kd = 0.0
        self._pid_speed.out_min = 0.0
        self._pid_speed.out_max = 320.0
        pi_hz = self._pid_speed.step(err, dt_s)
        return max(0.0, min(320.0, ff_hz + pi_hz))

    def speed_to_hz(self, setpoint_mpm: float, actual_mpm: float, dt_s: float) -> float:
        """Dispatch PID strategy based on pid_tune_method."""
        if self.uses_pi_feedforward():
            return self.pid_speed_to_hz_ff(setpoint_mpm, actual_mpm, dt_s)
        return self.pid_speed_to_hz(setpoint_mpm, actual_mpm, dt_s)

    def apply_pid_tune_method(self, method: str) -> None:
        self.params.pid_tune_method = parse_pid_tune_method(method)

    def apply_setpoint(self, name: str, value: float) -> None:
        # Minimal validation: ignore NaN/inf
        if not isfinite(value):
            return
        if name not in SETPOINTS:
            return

        # Special cases: unit conversion + roll geometry sync
        if name == "unwind_roll_length_m":
            self.params.unwind_roll_length_m = clamp(name, value)
            self.sync_start_diameter_from_roll_length()
            return
        if name == "start_diameter_mm":
            # Legacy SCADA: diameter in → store length out (and keep diameter).
            d = clamp(name, value) / 1000.0
            self.params.start_diameter_m = d
            self.params.unwind_roll_length_m = _length_from_diameter_m(
                d,
                self.params.core_diameter_m,
                self.params.material_thickness_m,
            )
            return
        if name == "material_thickness_mm":
            self.params.material_thickness_m = clamp(name, value) / 1000.0
            self.sync_start_diameter_from_roll_length()
            return
        if name == "core_diameter_mm":
            self.params.core_diameter_m = clamp(name, value) / 1000.0
            self.sync_start_diameter_from_roll_length()
            return
        if name == "roll_encoder_diameter_mm":
            self.params.roll_diameter_m = clamp(name, value) / 1000.0
            return
        if name == "encoder_invert":
            self.params.encoder_invert = bool(clamp(name, value))
            return

        sp = SETPOINTS[name]
        attr = sp.param_attr or name
        setattr(self.params, attr, clamp(name, value))

    def reset_pid(self) -> None:
        self._pid_speed.reset()
