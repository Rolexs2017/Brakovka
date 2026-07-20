from __future__ import annotations

from dataclasses import dataclass

from asyncua import Server, ua

from .commands import CommandSnapshot
from .config import OpcUaConfig
from .machine import Machine
from .setpoints import OPC_DEFS, ROLL_SETPOINT_KEYS, SETPOINTS


@dataclass(frozen=True)
class _SpVar:
    name: str
    getter: callable
    setpoint_key: str


@dataclass
class OpcUaHandles:
    # Telemetry
    state: any
    speed_mpm: any
    wound_m: any
    brake_pct: any
    tension_n: any
    unwind_diameter_mm: any
    start_diameter_mm: any
    encoder_error: any
    magnet_ok: any
    watchdog_fault: any
    modbus_error: any
    vfd_status_word: any
    vfd_error_code: any
    vfd_fault: any
    vfd_warning: any
    vfd_freq_cmd_hz: any
    vfd_freq_out_hz: any
    emu_consumer_diameter_mm: any
    ramp_speed_mpm: any
    wound_progress_pct: any

    # Commands
    cmd_start: any
    cmd_stop: any
    cmd_jog: any
    cmd_reverse: any
    cmd_reset_roll: any
    cmd_reset_wound: any
    cmd_apply_setpoints: any


def _param_getter(machine: Machine, key: str):
    sp = SETPOINTS[key]

    def getter() -> float:
        attr = sp.param_attr or key
        return float(getattr(machine.params, attr)) * sp.param_scale

    return getter


class OpcUaBridge:
    def __init__(self, machine: Machine, opcua: OpcUaConfig | None = None) -> None:
        self.machine = machine
        self._opcua = opcua or OpcUaConfig()
        self.server = Server()
        self.handles: OpcUaHandles | None = None
        self._sp_nodes: dict[str, any] = {}
        self._sp_seeded = False

        # command latches set by OPC-UA
        self._cmd_start = False
        self._cmd_stop = False
        self._cmd_reset_wound = False
        self._cmd_reset_roll = False
        self._cmd_jog = False
        self._cmd_reverse = False
        self._cmd_apply_setpoints = False
        self._last_telem: dict[str, object] = {}

    async def start(self) -> None:
        await self.server.init()
        self.server.set_endpoint(self._opcua.endpoint)
        self.server.set_server_name(self._opcua.server_name)

        uri = "urn:brakovka:pi"
        idx = await self.server.register_namespace(uri)

        root = self.server.nodes.objects
        obj = await root.add_object(idx, "Brakovka")

        telem = await obj.add_object(idx, "Telemetry")
        cmds = await obj.add_object(idx, "Commands")
        sps = await obj.add_object(idx, "Setpoints")

        h_state = await telem.add_variable(idx, "State", self.machine.telem.state.name)
        h_speed = await telem.add_variable(idx, "Speed_mpm", float(self.machine.telem.speed_mpm))
        h_wound = await telem.add_variable(idx, "Wound_m", float(self.machine.telem.wound_length_m))
        h_brake = await telem.add_variable(idx, "Brake_pct", float(self.machine.telem.brake_pressure_pct))
        h_tension = await telem.add_variable(idx, "Tension_N", float(self.machine.telem.tension_n))
        h_unwind_d = await telem.add_variable(idx, "UnwindDiameter_mm", float(self.machine.telem.unwind_diameter_mm))
        h_start_d = await telem.add_variable(
            idx, "StartDiameter_mm", float(self.machine.params.start_diameter_m * 1000.0)
        )
        h_encerr = await telem.add_variable(idx, "EncoderError", bool(self.machine.telem.encoder_error))
        h_magnet = await telem.add_variable(idx, "MagnetOk", bool(self.machine.telem.magnet_ok))
        h_wdog = await telem.add_variable(idx, "WatchdogFault", bool(self.machine.telem.watchdog_fault))
        h_modbus = await telem.add_variable(idx, "ModbusError", bool(self.machine.telem.modbus_error))
        h_vfd_sw = await telem.add_variable(idx, "VfdStatusWord", int(self.machine.telem.vfd_status_word))
        h_vfd_err = await telem.add_variable(idx, "VfdErrorCode", int(self.machine.telem.vfd_error_code))
        h_vfd_fault = await telem.add_variable(idx, "VfdFault", bool(self.machine.telem.vfd_fault))
        h_vfd_warn = await telem.add_variable(idx, "VfdWarning", bool(self.machine.telem.vfd_warning))
        h_vfd_fcmd = await telem.add_variable(idx, "VfdFreqCmd_Hz", float(self.machine.telem.vfd_freq_cmd_hz))
        h_vfd_fout = await telem.add_variable(idx, "VfdFreqOut_Hz", float(self.machine.telem.vfd_freq_out_hz))
        h_emu_dia = await telem.add_variable(idx, "EmuConsumerDiameter_mm", float(self.machine.telem.emu_consumer_diameter_mm))
        h_ramp = await telem.add_variable(idx, "RampSpeed_mpm", float(self.machine.telem.ramp_speed_mpm))
        h_wound_pct = await telem.add_variable(idx, "WoundProgress_pct", float(self.machine.telem.wound_progress_pct))

        for v in (
            h_state, h_speed, h_wound, h_brake, h_tension, h_unwind_d, h_start_d,
            h_encerr, h_magnet, h_wdog, h_modbus, h_vfd_sw, h_vfd_err, h_vfd_fault, h_vfd_warn, h_vfd_fcmd, h_vfd_fout, h_emu_dia,
            h_ramp, h_wound_pct,
        ):
            await v.set_writable(False)

        # Commands are writable by SCADA/HMI
        c_start = await cmds.add_variable(idx, "Start", False)
        c_stop = await cmds.add_variable(idx, "Stop", False)
        c_jog = await cmds.add_variable(idx, "Jog", False)
        c_rev = await cmds.add_variable(idx, "Reverse", False)
        c_reset_roll = await cmds.add_variable(idx, "ResetRoll", False)
        c_reset_wound = await cmds.add_variable(idx, "ResetWound", False)
        c_apply_sp = await cmds.add_variable(idx, "ApplySetpoints", False)
        for v in (c_start, c_stop, c_jog, c_rev, c_reset_roll, c_reset_wound, c_apply_sp):
            await v.set_writable(True)

        sp_defs: list[_SpVar] = [
            _SpVar(opc_name, _param_getter(self.machine, key), key)
            for opc_name, key in OPC_DEFS
        ]

        sp_nodes: dict[str, any] = {}
        for d in sp_defs:
            n = await sps.add_variable(idx, d.name, d.getter())
            await n.set_writable(True)
            sp_nodes[d.setpoint_key] = n
        self._sp_nodes = sp_nodes

        self.handles = OpcUaHandles(
            state=h_state,
            speed_mpm=h_speed,
            wound_m=h_wound,
            brake_pct=h_brake,
            tension_n=h_tension,
            unwind_diameter_mm=h_unwind_d,
            start_diameter_mm=h_start_d,
            encoder_error=h_encerr,
            magnet_ok=h_magnet,
            watchdog_fault=h_wdog,
            modbus_error=h_modbus,
            vfd_status_word=h_vfd_sw,
            vfd_error_code=h_vfd_err,
            vfd_fault=h_vfd_fault,
            vfd_warning=h_vfd_warn,
            vfd_freq_cmd_hz=h_vfd_fcmd,
            vfd_freq_out_hz=h_vfd_fout,
            emu_consumer_diameter_mm=h_emu_dia,
            ramp_speed_mpm=h_ramp,
            wound_progress_pct=h_wound_pct,
            cmd_start=c_start,
            cmd_stop=c_stop,
            cmd_jog=c_jog,
            cmd_reverse=c_rev,
            cmd_reset_roll=c_reset_roll,
            cmd_reset_wound=c_reset_wound,
            cmd_apply_setpoints=c_apply_sp,
        )

        await self.server.start()

    async def stop(self) -> None:
        await self.server.stop()

    def _current_machine_setpoints(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for _opc_name, key in OPC_DEFS:
            sp = SETPOINTS[key]
            attr = sp.param_attr or key
            out[key] = float(getattr(self.machine.params, attr)) * sp.param_scale
        return out

    async def sync_setpoints_from_machine(self) -> None:
        """Push Machine params into OPC nodes (after HMI save)."""
        if not self._sp_nodes:
            return
        values = self._current_machine_setpoints()
        for key, node in self._sp_nodes.items():
            if key not in values:
                continue
            # Nodes were created from Python float -> OPC Double; do not force Float.
            await node.write_value(float(values[key]))
        self._sp_seeded = True

    async def _read_all_setpoints(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, node in self._sp_nodes.items():
            out[key] = float(await node.read_value())
        return out

    def _apply_setpoint_map(self, values: dict[str, float], *, keys: tuple[str, ...] | None = None) -> None:
        for key, value in values.items():
            if keys is not None and key not in keys:
                continue
            self.machine.apply_setpoint(key, float(value))

    async def poll_commands_and_setpoints(self) -> None:
        if not self.handles:
            return
        h = self.handles
        # commands
        self._cmd_start = bool(await h.cmd_start.read_value())
        self._cmd_stop = bool(await h.cmd_stop.read_value())
        self._cmd_jog = bool(await h.cmd_jog.read_value())
        self._cmd_reverse = bool(await h.cmd_reverse.read_value())
        self._cmd_reset_roll = bool(await h.cmd_reset_roll.read_value())
        self._cmd_reset_wound = bool(await h.cmd_reset_wound.read_value())
        self._cmd_apply_setpoints = bool(await h.cmd_apply_setpoints.read_value())

        # First poll: skip apply (nodes already initialized from Machine).
        if not self._sp_seeded:
            self._sp_seeded = True
            return

        # SCADA: apply setpoints only on explicit command buttons.
        if self._cmd_apply_setpoints:
            node_values = await self._read_all_setpoints()
            self._apply_setpoint_map(node_values)
            return

        # ResetRoll from SCADA: apply roll-related setpoints from OPC, then reset.
        if self._cmd_reset_roll:
            node_values = await self._read_all_setpoints()
            self._apply_setpoint_map(node_values, keys=ROLL_SETPOINT_KEYS)

    async def clear_one_shots(self) -> None:
        if not self.handles:
            return
        h = self.handles
        # Treat Start/Stop/Reset*/ApplySetpoints as pulses: auto-clear after read.
        if self._cmd_start:
            await h.cmd_start.write_value(ua.Variant(False, ua.VariantType.Boolean))
        if self._cmd_stop:
            await h.cmd_stop.write_value(ua.Variant(False, ua.VariantType.Boolean))
        if self._cmd_reset_wound:
            await h.cmd_reset_wound.write_value(ua.Variant(False, ua.VariantType.Boolean))
        if self._cmd_reset_roll:
            await h.cmd_reset_roll.write_value(ua.Variant(False, ua.VariantType.Boolean))
        if self._cmd_apply_setpoints:
            await h.cmd_apply_setpoints.write_value(ua.Variant(False, ua.VariantType.Boolean))

    def snapshot_inputs(self) -> dict:
        return CommandSnapshot(
            start=self._cmd_start,
            stop=self._cmd_stop,
            jog=self._cmd_jog,
            reverse=self._cmd_reverse,
            reset_roll=self._cmd_reset_roll,
            reset_wound=self._cmd_reset_wound,
        ).as_dict()

    async def _write_if_changed(self, node, key: str, value: object) -> None:
        if self._last_telem.get(key) == value:
            return
        await node.write_value(value)
        self._last_telem[key] = value

    async def publish_telemetry(self) -> None:
        if not self.handles:
            return
        h = self.handles
        t = self.machine.telem
        # Round floats so noise does not force a write every tick.
        await self._write_if_changed(h.state, "state", t.state.name)
        await self._write_if_changed(h.speed_mpm, "speed_mpm", round(float(t.speed_mpm), 2))
        await self._write_if_changed(h.wound_m, "wound_m", round(float(t.wound_length_m), 2))
        await self._write_if_changed(h.brake_pct, "brake_pct", round(float(t.brake_pressure_pct), 1))
        await self._write_if_changed(h.tension_n, "tension_n", round(float(t.tension_n), 1))
        await self._write_if_changed(
            h.unwind_diameter_mm, "unwind_diameter_mm", round(float(t.unwind_diameter_mm), 1)
        )
        await self._write_if_changed(
            h.start_diameter_mm,
            "start_diameter_mm",
            round(float(self.machine.params.start_diameter_m * 1000.0), 1),
        )
        await self._write_if_changed(h.encoder_error, "encoder_error", bool(t.encoder_error))
        await self._write_if_changed(h.magnet_ok, "magnet_ok", bool(t.magnet_ok))
        await self._write_if_changed(h.watchdog_fault, "watchdog_fault", bool(t.watchdog_fault))
        await self._write_if_changed(h.modbus_error, "modbus_error", bool(t.modbus_error))
        await self._write_if_changed(h.vfd_status_word, "vfd_status_word", int(t.vfd_status_word))
        await self._write_if_changed(h.vfd_error_code, "vfd_error_code", int(t.vfd_error_code))
        await self._write_if_changed(h.vfd_fault, "vfd_fault", bool(t.vfd_fault))
        await self._write_if_changed(h.vfd_warning, "vfd_warning", bool(t.vfd_warning))
        await self._write_if_changed(
            h.vfd_freq_cmd_hz, "vfd_freq_cmd_hz", round(float(t.vfd_freq_cmd_hz), 2)
        )
        await self._write_if_changed(
            h.vfd_freq_out_hz, "vfd_freq_out_hz", round(float(t.vfd_freq_out_hz), 2)
        )
        await self._write_if_changed(
            h.emu_consumer_diameter_mm,
            "emu_consumer_diameter_mm",
            round(float(t.emu_consumer_diameter_mm), 1),
        )
        await self._write_if_changed(
            h.ramp_speed_mpm, "ramp_speed_mpm", round(float(t.ramp_speed_mpm), 2)
        )
        await self._write_if_changed(
            h.wound_progress_pct, "wound_progress_pct", round(float(t.wound_progress_pct), 1)
        )
