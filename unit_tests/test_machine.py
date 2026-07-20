"""Unit tests for roll geometry, setpoints, and machine state machine."""

from __future__ import annotations

import unittest

from brakovka_pi.commands import CommandSnapshot, merge_command_dicts
from brakovka_pi.machine import Inputs, Machine, MachineState
from brakovka_pi.roll_geometry import (
    remaining_length_m,
    start_diameter_from_length_m,
    unwind_diameter_m,
    wound_diameter_m,
)
from brakovka_pi.setpoints import clamp, machine_params_to_json, machine_params_to_ui
from brakovka_pi.state import MOVING_STATES, RUN_LIKE_STATES


class TestRollGeometry(unittest.TestCase):
    def test_start_diameter_from_length_matches_wound(self) -> None:
        core, t, length = 0.076, 0.0002, 2500.0
        d = start_diameter_from_length_m(core, t, length)
        self.assertAlmostEqual(d, wound_diameter_m(core, t, length), places=9)
        self.assertGreater(d, core)

    def test_remaining_roundtrip(self) -> None:
        core, t = 0.076, 0.0003
        d0 = 0.8
        length = remaining_length_m(d0, core, t)
        d_back = start_diameter_from_length_m(core, t, length)
        self.assertAlmostEqual(d_back, d0, places=6)

    def test_unwind_shrinks(self) -> None:
        d0, core, t = 0.8, 0.076, 0.0003
        d_half = unwind_diameter_m(d0, core, t, unwound_m=500.0)
        self.assertLess(d_half, d0)
        self.assertGreaterEqual(d_half, core)

    def test_zero_thickness_remaining(self) -> None:
        self.assertEqual(remaining_length_m(0.8, 0.076, 0.0), 0.0)


class TestSetpoints(unittest.TestCase):
    def test_clamp(self) -> None:
        self.assertEqual(clamp("speed_setpoint_mpm", -10), 0.0)
        self.assertEqual(clamp("speed_setpoint_mpm", 500), 300.0)
        self.assertEqual(clamp("speed_setpoint_mpm", 50), 50.0)

    def test_ui_and_json_maps(self) -> None:
        m = Machine()
        ui = machine_params_to_ui(m.params)
        self.assertIn("speed_set_mpm", ui)
        self.assertIn("unwind_roll_length_m", ui)
        self.assertAlmostEqual(ui["material_thickness_mm"], m.params.material_thickness_m * 1000.0)
        js = machine_params_to_json(m.params)
        self.assertIn("unwind_roll_length_m", js)
        self.assertIn("core_diameter_mm", js)


class TestMachineStateMachine(unittest.TestCase):
    def test_idle_to_run_to_stop(self) -> None:
        m = Machine()
        m.update_state(Inputs(start_pulse=True, estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.RUN)
        self.assertTrue(m.is_motion_active())
        self.assertFalse(m.allow_roll_edit())

        m.params.target_length_m = 10.0
        m.telem.wound_length_m = 10.0
        m.update_state(Inputs(estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.STOPPING)

        m.brake_until_t = 0.0
        m.update_state(Inputs(estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.IDLE)
        self.assertTrue(m.allow_roll_edit())

    def test_slowdown_enter(self) -> None:
        m = Machine()
        m.params.target_length_m = 100.0
        m.params.slowdown_start_pct = 90.0
        m.params.slowdown_exit_pct = 85.0
        m.telem.state = MachineState.RUN
        m.telem.wound_length_m = 91.0
        m.update_state(Inputs(estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.SLOWDOWN)
        self.assertIn(m.telem.state, RUN_LIKE_STATES)

    def test_slowdown_hysteresis(self) -> None:
        m = Machine()
        m.params.target_length_m = 100.0
        m.params.slowdown_start_pct = 90.0
        m.params.slowdown_exit_pct = 85.0
        m.telem.state = MachineState.RUN
        m.telem.wound_length_m = 91.0
        m.update_state(Inputs(estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.SLOWDOWN)

        m.telem.wound_length_m = 88.0
        m.update_state(Inputs(estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.SLOWDOWN)

        m.telem.wound_length_m = 84.0
        m.update_state(Inputs(estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.RUN)

    def test_jog_release_stops(self) -> None:
        m = Machine()
        m.update_state(Inputs(jog_level=True, estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.JOG)
        m.update_state(Inputs(jog_level=False, estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.STOPPING)

    def test_fault_blocks_start_and_stops_run(self) -> None:
        m = Machine()
        m.telem.modbus_error = True
        m.update_state(Inputs(start_pulse=True, estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.IDLE)

        m.telem.modbus_error = False
        m.update_state(Inputs(start_pulse=True, estop_ok=True))
        self.assertEqual(m.telem.state, MachineState.RUN)
        m.telem.vfd_fault = True
        self.assertTrue(m.fault_stop("test"))
        self.assertEqual(m.telem.state, MachineState.STOPPING)

    def test_calibrated_roll_diameter(self) -> None:
        from math import pi

        from brakovka_pi.encoder import COUNTS_PER_REV, calibrated_roll_diameter_m

        d = 0.08
        length = 10.0
        pulses = int(round(length * COUNTS_PER_REV / (pi * d)))
        d_back = calibrated_roll_diameter_m(length, pulses)
        self.assertIsNotNone(d_back)
        assert d_back is not None
        self.assertAlmostEqual(d_back, d, places=5)

    def test_unwind_length_setpoint_updates_diameter(self) -> None:
        m = Machine()
        m.apply_setpoint("material_thickness_mm", 0.2)
        m.apply_setpoint("core_diameter_mm", 76.0)
        m.apply_setpoint("unwind_roll_length_m", 1000.0)
        expected = start_diameter_from_length_m(0.076, 0.0002, 1000.0)
        self.assertAlmostEqual(m.params.start_diameter_m, expected, places=6)
        self.assertAlmostEqual(m.remaining_length_m(), 1000.0)

    def test_remaining_after_unwind(self) -> None:
        m = Machine()
        m.apply_setpoint("unwind_roll_length_m", 500.0)
        m.apply_new_unwind_roll()
        m.telem.unwind_length_m = 50.0
        self.assertAlmostEqual(m.remaining_length_m(), 450.0)


class TestCommands(unittest.TestCase):
    def test_merge_or(self) -> None:
        a = {"start": True, "jog": False}
        b = {"jog": True, "stop": False}
        c = merge_command_dicts(a, b)
        self.assertIsInstance(c, CommandSnapshot)
        self.assertTrue(c.start)
        self.assertTrue(c.jog)
        self.assertFalse(c.stop)

    def test_moving_states(self) -> None:
        self.assertEqual(
            MOVING_STATES,
            frozenset(
                {
                    MachineState.RUN,
                    MachineState.JOG,
                    MachineState.REVERSE,
                    MachineState.SLOWDOWN,
                }
            ),
        )


class TestPidAndRamp(unittest.TestCase):
    def test_ramp_accelerates(self) -> None:
        m = Machine()
        m.telem.state = MachineState.RUN
        m.params.speed_setpoint_mpm = 60.0
        m.params.accel_time_s = 10.0
        v1 = m.update_speed_ramp(0.1)
        v2 = m.update_speed_ramp(0.1)
        self.assertGreater(v2, v1)
        self.assertLessEqual(v2, 60.0)

    def test_idle_ramp_zero(self) -> None:
        m = Machine()
        m._ramp_speed_mpm = 40.0
        self.assertEqual(m.update_speed_ramp(0.1), 0.0)


if __name__ == "__main__":
    unittest.main()
