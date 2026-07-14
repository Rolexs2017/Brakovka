from __future__ import annotations

import asyncio
import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

from .brake_pwm import BrakePwm
from .commands import merge_command_dicts
from .config import load_runtime_config, resolve_emulator
from .encoder import Encoder
from .emulation import EmulatedVfd, SimEncoder
from .gpio_io import GpioInputs
from .logutil import setup_logging
from .machine import Inputs, Machine
from .modbus_rs485 import Rs485Vfd, VfdCommand
from .opcua_srv import OpcUaBridge
from .state import MachineState, RUN_LIKE_STATES

if TYPE_CHECKING:
    from brakovka_hmi.bridge import LocalBridge

log = logging.getLogger(__name__)
machine_log = logging.getLogger("brakovka.machine")


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
    enc_emu: SimEncoder | None = None
    if emulator:
        enc_emu = SimEncoder(
            mpm_per_hz=m.params.emu_mpm_per_hz,
            gear_ratio=float(emu_cfg.get("gear_ratio", 20.0)),
            motor_rpm_per_hz=m.params.emu_motor_rpm_per_hz,
            consumer_core_diameter_m=m.params.core_diameter_m,
            thickness_m=m.params.material_thickness_m,
        )
        encoder = enc_emu
    else:
        enc_hw = Encoder(
            roll_diameter_m=m.params.roll_diameter_m,
            spike_threshold_m=m.params.encoder_spike_m,
        )
        encoder = enc_hw

    try:
        last_freq_cmd = 0.0
        prev_reset_wound = False
        prev_reset_roll = False
        last_brake_pct = 0.0
        prev_state = m.telem.state
        prev_encoder_error = False
        prev_vfd_fault = False
        prev_vfd_warning = False
        last_task_ok_t = monotonic()
        watchdog_limit_s = float(timing_cfg.watchdog_limit_s)

        p_task = _Periodic(timing_cfg.task_period_s)
        p_opc_poll = _Periodic(timing_cfg.opcua_poll_period_s)
        p_opc_pub = _Periodic(timing_cfg.opcua_publish_period_s)
        p_vfd_poll = _Periodic(timing_cfg.vfd_status_poll_period_s)
        p_vfd_cmd = _Periodic(timing_cfg.vfd_cmd_period_s)
        p_status_log = _Periodic(5.0)

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
                if enc_hw is not None:
                    enc_hw.set_roll_diameter_m(m.params.roll_diameter_m)
                if enc_emu is not None:
                    enc_emu.mpm_per_hz = m.params.emu_mpm_per_hz
                    enc_emu.thickness_m = m.params.material_thickness_m

            inp_gpio = gpio.read()
            if hmi_bridge is not None:
                hmi_bridge.publish_gpio_levels(gpio.read_levels())
            sources = [opc.snapshot_inputs()]
            if hmi_bridge is not None:
                sources.append(hmi_bridge.snapshot_inputs())
            inp = _merge_inputs(inp_gpio, *sources)

            if p_task.due(now):
                task_start = now
                io_wait_s = 0.0
                gap_s = task_start - last_task_ok_t
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
                    machine_log.info(
                        "Reset roll: length=%.0f m diameter=%.0f mm remaining=%.1f m",
                        m.params.unwind_roll_length_m,
                        m.telem.unwind_diameter_mm,
                        m.remaining_length_m(),
                    )
                if inp.reset_wound_pulse and not prev_reset_wound:
                    encoder.reset_wound()
                    m.reset_pid()
                    machine_log.info("Reset wound length")

                if inp.start_pulse:
                    machine_log.info("Command START")
                if inp.stop_pulse:
                    machine_log.info("Command STOP")

                state = m.telem.state
                forward = state != MachineState.REVERSE
                wound_enable = state in RUN_LIKE_STATES
                if emulator:
                    e = encoder.step(
                        timing_cfg.task_period_s,
                        last_freq_cmd,
                        forward=forward,
                        wound_enable=wound_enable,
                    )
                    m.telem.speed_mpm = float(e["speed_mpm"])
                    m.telem.wound_length_m = float(e["wound_m"])
                    m.telem.unwind_length_m = float(e["unwind_m"])
                    m.telem.emu_consumer_diameter_mm = float(
                        e.get("consumer_diameter_mm", 0.0)
                    )
                    m.telem.encoder_error = not bool(e["ok"])
                    m.telem.magnet_ok = bool(e.get("magnet_ok", True))
                else:
                    e = encoder.step(
                        timing_cfg.task_period_s,
                        forward=forward,
                        wound_enable=wound_enable,
                    )
                    m.telem.speed_mpm = float(e.speed_mpm)
                    m.telem.wound_length_m = float(e.wound_m)
                    m.telem.unwind_length_m = float(e.unwind_m)
                    m.telem.encoder_error = not bool(e.ok)
                    m.telem.magnet_ok = bool(e.magnet_ok)

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

                sp_mpm = m.update_speed_ramp(timing_cfg.task_period_s)
                actual_mpm = m.telem.speed_mpm
                stopping = state == MachineState.STOPPING
                freq_cmd_hz = m.pid_speed_to_hz(
                    sp_mpm, actual_mpm, timing_cfg.task_period_s
                )

                should_send = (
                    emulator
                    or stopping
                    or p_vfd_cmd.due(now)
                    or abs(freq_cmd_hz - last_freq_cmd) >= timing_cfg.vfd_cmd_min_delta_hz
                )

                if should_send:
                    p_vfd_cmd.arm_next(now)
                    last_freq_cmd = freq_cmd_hz

                    vfd_cmd = VfdCommand(
                        run=(not stopping) and sp_mpm > 0.01 and inp.estop_ok,
                        reverse=(state == MachineState.REVERSE),
                        speed_setpoint_hz=freq_cmd_hz,
                    )
                    t_io = monotonic()
                    write_ok = await vfd.write_command(vfd_cmd)
                    io_wait_s += monotonic() - t_io
                    m.telem.vfd_freq_cmd_hz = freq_cmd_hz
                    if not emulator and write_ok is False:
                        if not m.telem.modbus_error:
                            machine_log.error("Modbus write failed")
                        m.telem.modbus_error = True
                        await vfd.reconnect()

                unwind_diameter_m = m.unwind_diameter_m()
                m.telem.unwind_diameter_mm = unwind_diameter_m * 1000.0
                m.telem.tension_n = m.calc_tension_n(last_brake_pct)

                if m.tension_control_enabled():
                    tension_brake_pct = m.tension_brake_command_pct()
                else:
                    tension_brake_pct = 0.0

                brake_pct = m.brake_pressure_pct(tension_brake_pct)
                brake.set_pressure_pct(brake_pct)
                m.telem.brake_pressure_pct = brake_pct
                last_brake_pct = brake_pct

                # Exclude Modbus I/O from compute time — timeouts are modbus_error, not watchdog.
                task_elapsed = monotonic() - task_start - io_wait_s
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
                    t_io = monotonic()
                    write_ok = await vfd.write_command(
                        VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0)
                    )
                    io_wait_s += monotonic() - t_io
                    m.telem.vfd_freq_cmd_hz = 0.0
                    if not emulator and write_ok is False:
                        m.telem.modbus_error = True
                elif gap_s <= watchdog_limit_s and m.telem.watchdog_fault:
                    machine_log.info("Watchdog cleared")
                    m.telem.watchdog_fault = False

                last_task_ok_t = monotonic()

                if p_status_log.due(now):
                    p_status_log.arm_next(now)
                    machine_log.info(
                        "Status state=%s speed=%.1f mpm wound=%.2f m "
                        "dia=%.0f mm rem=%.1f m brake=%.1f%% freq=%.1f Hz",
                        m.telem.state.name,
                        m.telem.speed_mpm,
                        m.telem.wound_length_m,
                        m.telem.unwind_diameter_mm,
                        m.remaining_length_m(),
                        m.telem.brake_pressure_pct,
                        m.telem.vfd_freq_cmd_hz,
                    )

            if p_vfd_poll.due(now):
                p_vfd_poll.arm_next(now)
                st = await vfd.read_status()
                if st:
                    m.telem.vfd_status_word = int(st.get("status_word", 0))
                    m.telem.vfd_error_code = int(st.get("error_code", 0))
                    m.telem.vfd_freq_out_hz = float(st.get("freq_out_hz", 0.0))
                    m.telem.vfd_fault = bool(st.get("fault", False))
                    m.telem.vfd_warning = bool(st.get("warning", False))
                    if not emulator and m.telem.modbus_error:
                        machine_log.info("Modbus link restored")
                    if not emulator:
                        m.telem.modbus_error = False

                    if m.telem.vfd_fault and not prev_vfd_fault:
                        machine_log.error(
                            "VFD fault code=%s status=0x%04X",
                            m.telem.vfd_error_code,
                            m.telem.vfd_status_word,
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
                elif not emulator:
                    if not m.telem.modbus_error:
                        machine_log.error("Modbus communication error (no response)")
                    m.telem.modbus_error = True

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
            await vfd.write_command(
                VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0)
            )
        except Exception:
            machine_log.exception("VFD stop command failed")
        if enc_hw is not None:
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
