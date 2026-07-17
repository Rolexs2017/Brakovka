from __future__ import annotations

import asyncio
import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

from .brake_pwm import BrakePwm
from .commands import merge_command_dicts
from .config import load_runtime_config, resolve_emulator
from .encoder import (
    Encoder,
    PID_REGULATOR_SPEED_AVG_N,
    SpeedMovingAverage,
    SpeedOutlierReject,
    ThreadedEncoder,
    speed_mpm_from_length_delta,
)
from .emulation import EmulatedVfd, SimEncoder
from .gpio_io import GpioInputs
from .logutil import setup_logging
from .machine import Inputs, Machine
from .modbus_rs485 import Rs485Vfd, VfdCommand
from .opcua_srv import OpcUaBridge
from .pid_autotune import AutotunePhase, PidAutotuner
from .pid_tune import PidTuneMethod, StepResponseAutotuner, parse_pid_tune_method
from .setpoints import SETPOINTS, machine_params_to_json
from .settings import save_machine_section
from .state import MachineState
from .vfd_io import AsyncVfdBridge

if TYPE_CHECKING:
    from brakovka_hmi.bridge import LocalBridge

log = logging.getLogger(__name__)
machine_log = logging.getLogger("brakovka.machine")


def _make_pid_autotuner(m: Machine) -> PidAutotuner | StepResponseAutotuner:
    method = parse_pid_tune_method(m.params.pid_tune_method)
    kp_lo = SETPOINTS["pid_kp"].lo
    kp_hi = SETPOINTS["pid_kp"].hi
    ti_lo = SETPOINTS["pid_ti"].lo
    ti_hi = SETPOINTS["pid_ti"].hi
    kd_lo = SETPOINTS["pid_kd"].lo
    kd_hi = SETPOINTS["pid_kd"].hi

    if method == PidTuneMethod.RELAY.value:
        bias_scale = 1.0 / max(float(m.params.emu_mpm_per_hz), 0.1)
        return PidAutotuner(
            setpoint_mpm=float(m.params.jog_speed_mpm),
            relay_amp_hz=8.0,
            hysteresis_mpm=0.3,
            min_cycles=3,
            timeout_s=45.0,
            ramp_s=3.0,
            bias_hz_per_mpm=bias_scale,
            kp_lo=kp_lo,
            kp_hi=kp_hi,
            ti_lo=ti_lo,
            ti_hi=ti_hi,
            kd_lo=kd_lo,
            kd_hi=kd_hi,
        )

    est_gain = max(0.1, float(m.params.mpm_per_hz))
    if method != PidTuneMethod.PI_FF.value:
        est_gain = max(0.1, float(m.params.emu_mpm_per_hz))
    step_hz = max(8.0, min(24.0, float(m.params.jog_speed_mpm) / est_gain))
    return StepResponseAutotuner(
        mode=method,
        step_hz=step_hz,
        baseline_s=2.0,
        step_duration_s=10.0,
        timeout_s=40.0,
        kp_lo=kp_lo,
        kp_hi=kp_hi,
        ti_lo=ti_lo,
        ti_hi=ti_hi,
        kd_lo=kd_lo,
        kd_hi=kd_hi,
    )


def _merge_inputs(gpio_inp: Inputs, *sources: dict) -> Inputs:
    cmd = merge_command_dicts(
        {
            "start": gpio_inp.start_pulse,
            "stop": gpio_inp.stop_pulse,
            "jog": gpio_inp.jog_level,
            "reverse": gpio_inp.reverse_level,
            "reset_roll": gpio_inp.reset_roll_pulse,
            "reset_wound": gpio_inp.reset_wound_pulse,
        },
        *sources,
    )
    return Inputs(
        start_pulse=cmd.start,
        stop_pulse=cmd.stop,
        jog_level=cmd.jog,
        reverse_level=cmd.reverse,
        estop_ok=gpio_inp.estop_ok,
        reset_roll_pulse=cmd.reset_roll,
        reset_wound_pulse=cmd.reset_wound,
    )


class _Periodic:
    def __init__(self, period_s: float) -> None:
        self.period_s = max(1e-6, float(period_s))
        self.next_t = monotonic()

    def due(self, now: float) -> bool:
        return now >= self.next_t

    def arm_next(self, now: float) -> None:
        self.next_t = now + self.period_s


async def run_controller(
    *,
    hmi_bridge: LocalBridge | None = None,
    stop_event: asyncio.Event | None = None,
    hmi_ready: threading.Event | None = None,
    gpio: GpioInputs | None = None,
) -> None:
    """Main control loop. Optional LocalBridge merges HMI commands with GPIO/OPC.

    ``gpio`` may be pre-created on the main thread (recommended with Qt HMI).
    """
    emu_from_file, gpio_cfg, serial_cfg, vfd_cfg, opcua_cfg, timing_cfg, machine_cfg, emu_cfg = (
        load_runtime_config()
    )
    m = Machine()
    machine_cfg.apply_to(m)
    gpio = gpio if gpio is not None else GpioInputs(gpio_cfg)
    brake = BrakePwm(gpio_cfg)
    emulator = resolve_emulator(emu_from_file)
    vfd = EmulatedVfd() if emulator else Rs485Vfd(serial_cfg, vfd_cfg)
    opc = OpcUaBridge(m, opcua_cfg)

    if hmi_bridge is not None:
        # Publish before ready_event so Status screen does not show empty "unknown" GPIO.
        hmi_bridge.publish_gpio_levels(gpio.read_levels())
        hmi_bridge.attach(m, emulator=emulator, ready_event=hmi_ready)

    await vfd.connect()
    if not emulator and not vfd.connected:
        m.telem.modbus_error = True
        machine_log.error("Modbus: serial port not connected")
    await opc.start()

    vfd_io = AsyncVfdBridge(
        vfd,
        cmd_period_s=timing_cfg.vfd_cmd_period_s,
        poll_period_s=timing_cfg.vfd_status_poll_period_s,
        min_delta_hz=timing_cfg.vfd_cmd_min_delta_hz,
    )
    await vfd_io.start()
    if not emulator:
        machine_log.info("VFD Modbus I/O in background task (PID not blocked)")

    log.info(
        "Controller started (emulator=%s, hmi=%s, gpio_buttons=%s, pin_factory=%s)",
        emulator,
        hmi_bridge is not None,
        gpio.available,
        gpio.pin_factory or "-",
    )
    if not gpio.available and gpio.error:
        log.warning("GPIO buttons unavailable: %s", gpio.error)
    if emulator and gpio.available:
        log.info(
            "Emulator mode: virtual VFD/encoder; physical GPIO buttons remain active"
        )
    machine_log.info(
        "Machine ready: speed_sp=%.1f mpm target=%.0f m roll_len=%.0f m start_dia=%.0f mm",
        m.params.speed_setpoint_mpm,
        m.params.target_length_m,
        m.params.unwind_roll_length_m,
        m.params.start_diameter_m * 1000.0,
    )

    enc_hw: Encoder | None = None
    enc_thread: ThreadedEncoder | None = None
    enc_emu: SimEncoder | None = None
    if emulator:
        enc_emu = SimEncoder(
            gear_ratio=float(emu_cfg.get("gear_ratio", 20.0)),
            motor_rpm_per_hz=m.params.emu_motor_rpm_per_hz,
            consumer_core_diameter_m=m.params.core_diameter_m,
            thickness_m=m.params.material_thickness_m,
            roll_diameter_m=m.params.roll_diameter_m,
        )
        encoder = enc_emu
    else:
        enc_hw = Encoder(
            roll_diameter_m=m.params.roll_diameter_m,
            spike_threshold_m=m.params.encoder_spike_m,
            max_speed_mpm=m.params.max_ramp_speed_mpm,
            invert=m.params.encoder_invert,
        )
        enc_thread = ThreadedEncoder(enc_hw)
        enc_thread.start()
        encoder = enc_thread
        machine_log.info("Hardware encoder in dedicated thread (max I2C poll rate)")

    try:
        last_freq_cmd = 0.0
        prev_reset_wound = False
        prev_reset_roll = False
        last_brake_pct = 0.0
        prev_state = m.telem.state
        prev_encoder_error = False
        prev_vfd_fault = False
        prev_vfd_warning = False
        prev_modbus_error = False
        last_task_ok_t = monotonic()
        watchdog_limit_s = float(timing_cfg.watchdog_limit_s)
        autotuner: PidAutotuner | StepResponseAutotuner | None = None
        pid_speed_avg = SpeedMovingAverage(PID_REGULATOR_SPEED_AVG_N)
        speed_outlier = SpeedOutlierReject(max_mpm=m.params.max_ramp_speed_mpm)
        prev_wound_length_m: float | None = None
        last_speed_mpm = 0.0

        p_task = _Periodic(timing_cfg.task_period_s)
        p_opc_poll = _Periodic(timing_cfg.opcua_poll_period_s)
        p_opc_pub = _Periodic(timing_cfg.opcua_publish_period_s)

        while True:
            if stop_event is not None and stop_event.is_set():
                break

            now = monotonic()

            if p_opc_poll.due(now):
                p_opc_poll.arm_next(now)
                # HMI Save/Reset applied params to Machine — push them to OPC nodes
                # before reading SCADA setpoints, so stale OPC values cannot overwrite UI.
                if hmi_bridge is not None and hmi_bridge.take_opc_sync_pending():
                    await opc.sync_setpoints_from_machine()
                    machine_log.info(
                        "HMI setpoints applied: speed=%.1f mpm target=%.0f m "
                        "roll_len=%.0f m start_dia=%.0f mm thickness=%.3f mm",
                        m.params.speed_setpoint_mpm,
                        m.params.target_length_m,
                        m.params.unwind_roll_length_m,
                        m.params.start_diameter_m * 1000.0,
                        m.params.material_thickness_m * 1000.0,
                    )
                await opc.poll_commands_and_setpoints()
                await opc.clear_one_shots()
                speed_outlier.set_max_mpm(m.params.max_ramp_speed_mpm)
                if enc_thread is not None:
                    enc_thread.set_roll_diameter_m(m.params.roll_diameter_m)
                    enc_thread.set_max_speed_mpm(m.params.max_ramp_speed_mpm)
                    enc_thread.set_invert(m.params.encoder_invert)
                if enc_emu is not None:
                    enc_emu.thickness_m = m.params.material_thickness_m
                    enc_emu.roll_diameter_m = max(0.001, float(m.params.roll_diameter_m))
                    enc_emu.motor_rpm_per_hz = max(
                        0.01, float(m.params.emu_motor_rpm_per_hz)
                    )

            inp_gpio = gpio.read()
            if hmi_bridge is not None:
                hmi_bridge.publish_gpio_levels(gpio.read_levels())
            sources = [opc.snapshot_inputs()]
            if hmi_bridge is not None:
                sources.append(hmi_bridge.snapshot_inputs())
            inp = _merge_inputs(inp_gpio, *sources)

            if p_task.due(now):
                task_start = now
                gap_s = task_start - last_task_ok_t
                ctrl_dt = gap_s if gap_s > 1e-4 else timing_cfg.task_period_s
                ctrl_dt = min(max(ctrl_dt, 1e-4), 0.5)
                if gap_s > watchdog_limit_s:
                    if not m.telem.watchdog_fault:
                        machine_log.error(
                            "Watchdog fault: task gap=%.3f s (limit=%.3f s)",
                            gap_s,
                            watchdog_limit_s,
                        )
                    m.telem.watchdog_fault = True
                    if m.telem.state not in (MachineState.IDLE, MachineState.STOPPING):
                        m._enter_stopping()

                p_task.arm_next(now)

                if inp.reset_roll_pulse and not prev_reset_roll:
                    # Apply assigned unwind roll length; diameter is calculated.
                    encoder.reset_unwind()
                    m.apply_new_unwind_roll()
                    m.reset_pid()
                    pid_speed_avg.reset(0.0)
                    speed_outlier.reset(0.0)
                    prev_wound_length_m = None
                    machine_log.info(
                        "Reset roll: length=%.0f m diameter=%.0f mm remaining=%.1f m",
                        m.params.unwind_roll_length_m,
                        m.telem.unwind_diameter_mm,
                        m.remaining_length_m(),
                    )
                if inp.reset_wound_pulse and not prev_reset_wound:
                    encoder.reset_wound()
                    m.reset_pid()
                    pid_speed_avg.reset(0.0)
                    speed_outlier.reset(0.0)
                    prev_wound_length_m = None
                    machine_log.info("Reset wound length")

                if inp.start_pulse:
                    machine_log.info("Command START")
                if inp.stop_pulse:
                    machine_log.info("Command STOP")

                state = m.telem.state
                forward = state != MachineState.REVERSE
                # Мерный ролик считает факт движения всегда (в т.ч. IDLE — калибровка).
                wound_enable = True
                if emulator:
                    e = encoder.step(
                        ctrl_dt,
                        last_freq_cmd,
                        forward=forward,
                        wound_enable=wound_enable,
                    )
                    wound_m = float(e["wound_m"])
                    m.telem.wound_length_m = wound_m
                    m.telem.unwind_length_m = float(e["unwind_m"])
                    m.telem.encoder_pulses = int(e["pulses"])
                    m.telem.emu_consumer_diameter_mm = float(
                        e.get("consumer_diameter_mm", 0.0)
                    )
                    encoder_ok = bool(e["ok"])
                    m.telem.encoder_error = not encoder_ok
                    m.telem.magnet_ok = True
                else:
                    assert enc_thread is not None
                    enc_thread.set_wound_enable(wound_enable)
                    e = enc_thread.snapshot()
                    wound_m = float(e.wound_m)
                    m.telem.wound_length_m = wound_m
                    m.telem.unwind_length_m = float(e.unwind_m)
                    m.telem.encoder_pulses = int(e.pulses)
                    encoder_ok = bool(e.ok)
                    m.telem.encoder_error = not encoder_ok
                    m.telem.magnet_ok = bool(e.magnet_ok)

                if encoder_ok:
                    if prev_wound_length_m is not None:
                        last_speed_mpm = speed_mpm_from_length_delta(
                            wound_m - prev_wound_length_m,
                            ctrl_dt,
                        )
                    else:
                        last_speed_mpm = 0.0
                    prev_wound_length_m = wound_m

                m.update_state(inp)
                prev_reset_wound = inp.reset_wound_pulse
                prev_reset_roll = inp.reset_roll_pulse

                state = m.telem.state
                entered_stopping = (
                    state == MachineState.STOPPING and prev_state != MachineState.STOPPING
                )
                if state != prev_state:
                    machine_log.info("State %s -> %s", prev_state.name, state.name)
                    if entered_stopping:
                        machine_log.info(
                            "STOP: motor cut, brake 100%% for %.1f s",
                            m.params.brake_delay_s,
                        )
                    prev_state = state

                if m.telem.encoder_error and not prev_encoder_error:
                    machine_log.error("Encoder error")
                elif not m.telem.encoder_error and prev_encoder_error:
                    machine_log.info("Encoder recovered")
                prev_encoder_error = m.telem.encoder_error

                clean_mpm = speed_outlier.update(last_speed_mpm)
                actual_mpm = pid_speed_avg.update(clean_mpm)
                m.telem.speed_mpm = actual_mpm
                stopping = state == MachineState.STOPPING

                # --- PID autotune or normal ramp+PID ---
                if m.telem.autotune_active:
                    if autotuner is None:
                        method = parse_pid_tune_method(m.params.pid_tune_method)
                        autotuner = _make_pid_autotuner(m)
                        autotuner.start()
                        machine_log.info(
                            "PID autotune started: method=%s jog=%.1f mpm",
                            method,
                            m.params.jog_speed_mpm,
                        )
                    tune = autotuner.step(actual_mpm, ctrl_dt)
                    m.telem.autotune_message = tune.message
                    freq_cmd_hz = float(tune.freq_hz)
                    run_cmd = bool(tune.run) and inp.estop_ok and not stopping
                    if tune.finished:
                        if tune.phase == AutotunePhase.DONE and tune.result is not None:
                            r = tune.result
                            m.apply_setpoint("pid_kp", r.kp)
                            m.apply_setpoint("pid_ti", r.ti)
                            m.apply_setpoint("pid_kd", r.kd)
                            if r.mpm_per_hz is not None:
                                m.apply_setpoint("mpm_per_hz", r.mpm_per_hz)
                            try:
                                save_machine_section(machine_params_to_json(m.params))
                            except Exception:
                                machine_log.exception("Failed to persist autotuned PID")
                            m.finish_autotune_ok(tune.message)
                            machine_log.info(
                                "PID autotune OK: kp=%.3f ti=%.3f kd=%.3f ku=%.3f pu=%.3f",
                                r.kp,
                                r.ti,
                                r.kd,
                                r.ku,
                                r.pu_s,
                            )
                            if hmi_bridge is not None:
                                hmi_bridge.mark_opc_sync_pending()
                        elif tune.phase == AutotunePhase.ABORTED:
                            if m.telem.autotune_active:
                                m.abort_autotune(tune.message)
                            machine_log.warning("PID autotune aborted: %s", tune.message)
                        else:
                            m.finish_autotune_fail(tune.message or "Ошибка автонастройки")
                            machine_log.error("PID autotune failed: %s", tune.message)
                        autotuner = None
                        freq_cmd_hz = 0.0
                        run_cmd = False
                    sp_mpm = float(m.params.jog_speed_mpm) if run_cmd else 0.0
                else:
                    if autotuner is not None:
                        autotuner = None
                    sp_mpm = m.update_speed_ramp(ctrl_dt)
                    raw_freq_cmd_hz = m.speed_to_hz(sp_mpm, actual_mpm, ctrl_dt)
                    run_cmd = (not stopping) and sp_mpm > 0.01 and inp.estop_ok
                    if not run_cmd or stopping or entered_stopping:
                        freq_cmd_hz = 0.0
                    else:
                        freq_cmd_hz = raw_freq_cmd_hz

                last_freq_cmd = freq_cmd_hz
                m.telem.vfd_freq_cmd_hz = freq_cmd_hz

                vfd_cmd = VfdCommand(
                    run=run_cmd,
                    reverse=(state == MachineState.REVERSE) and not m.telem.autotune_active,
                    speed_setpoint_hz=freq_cmd_hz,
                )
                vfd_io.set_command(vfd_cmd, force=stopping or entered_stopping)

                unwind_diameter_m = m.unwind_diameter_m()
                m.telem.unwind_diameter_mm = unwind_diameter_m * 1000.0
                m.telem.tension_n = m.calc_tension_n(last_brake_pct)

                if m.telem.autotune_active:
                    tension_brake_pct = 0.0
                elif m.tension_control_enabled():
                    tension_brake_pct = m.tension_brake_command_pct()
                else:
                    tension_brake_pct = 0.0

                brake_pct = m.brake_pressure_pct(tension_brake_pct)
                brake.set_pressure_pct(brake_pct)
                m.telem.brake_pressure_pct = brake_pct
                last_brake_pct = brake_pct

                # Apply latest VFD status from background I/O (no await).
                io = vfd_io.snapshot()
                m.telem.vfd_status_word = io.status_word
                m.telem.vfd_error_code = io.error_code
                m.telem.vfd_freq_out_hz = io.freq_out_hz
                m.telem.vfd_fault = io.fault
                m.telem.vfd_warning = io.warning

                if not emulator:
                    if not io.write_ok or not io.read_ok:
                        if not m.telem.modbus_error:
                            if not io.write_ok:
                                machine_log.error("Modbus write failed")
                            if not io.read_ok:
                                machine_log.error("Modbus communication error (no response)")
                        was_modbus = m.telem.modbus_error
                        m.telem.modbus_error = True
                        if not was_modbus and m.fault_stop("Modbus lost"):
                            machine_log.error("Fault stop: Modbus communication error")
                            vfd_io.set_command(
                                VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0),
                                force=True,
                            )
                    else:
                        if m.telem.modbus_error:
                            machine_log.info("Modbus link restored")
                        m.telem.modbus_error = False

                    if m.telem.vfd_fault and not prev_vfd_fault:
                        machine_log.error(
                            "VFD fault code=%s status=0x%04X",
                            m.telem.vfd_error_code,
                            m.telem.vfd_status_word,
                        )
                        if m.fault_stop("VFD fault"):
                            machine_log.error("Fault stop: VFD fault")
                            vfd_io.set_command(
                                VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0),
                                force=True,
                            )
                    elif not m.telem.vfd_fault and prev_vfd_fault:
                        machine_log.info("VFD fault cleared")
                    prev_vfd_fault = m.telem.vfd_fault

                    if m.telem.vfd_warning and not prev_vfd_warning:
                        machine_log.warning(
                            "VFD warning status=0x%04X",
                            m.telem.vfd_status_word,
                        )
                    prev_vfd_warning = m.telem.vfd_warning

                    if not m.telem.modbus_error and prev_modbus_error:
                        machine_log.info("Modbus error cleared")
                    prev_modbus_error = m.telem.modbus_error

                task_elapsed = monotonic() - task_start
                if task_elapsed > watchdog_limit_s:
                    if not m.telem.watchdog_fault:
                        machine_log.error(
                            "Watchdog fault: task compute=%.3f s (limit=%.3f s)",
                            task_elapsed,
                            watchdog_limit_s,
                        )
                    m.telem.watchdog_fault = True
                    if m.telem.state not in (MachineState.IDLE, MachineState.STOPPING):
                        m._enter_stopping()
                    vfd_io.set_command(
                        VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0),
                        force=True,
                    )
                    m.telem.vfd_freq_cmd_hz = 0.0
                elif gap_s <= watchdog_limit_s and m.telem.watchdog_fault:
                    machine_log.info("Watchdog cleared")
                    m.telem.watchdog_fault = False

                last_task_ok_t = monotonic()

            if p_opc_pub.due(now):
                p_opc_pub.arm_next(now)
                await opc.publish_telemetry()

            await asyncio.sleep(timing_cfg.task_period_s)

    except Exception:
        machine_log.exception("Controller loop crashed")
        raise
    finally:
        try:
            brake.set_pressure_pct(0.0)
            brake.close()
        except Exception:
            machine_log.exception("Brake shutdown failed")
        try:
            await vfd_io.stop()
        except Exception:
            machine_log.exception("VFD I/O stop failed")
        if enc_thread is not None:
            try:
                enc_thread.close()
            except Exception:
                machine_log.exception("Encoder thread shutdown failed")
        elif enc_hw is not None:
            try:
                enc_hw.close()
            except Exception:
                machine_log.exception("Encoder close failed")
        if hmi_bridge is not None:
            hmi_bridge.detach()
        try:
            await opc.stop()
        except Exception:
            machine_log.exception("OPC-UA stop failed")
        try:
            await vfd.close()
        except Exception:
            machine_log.exception("VFD close failed")
        log.info("Controller stopped")
        machine_log.info("Machine stopped")


async def main() -> None:
    setup_logging()
    await run_controller()
