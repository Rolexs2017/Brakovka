"""Unit tests for PID relay autotune (Åström–Hägglund + Ziegler–Nichols)."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from brakovka_pi.pid_autotune import (
    AutotunePhase,
    PidAutotuner,
    zn_pid_from_relay,
)


class TestZnFormula(unittest.TestCase):
    def test_zn_pid_from_relay(self) -> None:
        r = zn_pid_from_relay(relay_amp_hz=8.0, speed_amp_mpm=2.0, period_s=2.0)
        self.assertIsNotNone(r)
        assert r is not None
        ku = (4.0 * 8.0) / (math.pi * 2.0)
        self.assertAlmostEqual(r.ku, ku, places=6)
        self.assertAlmostEqual(r.kp, 0.6 * ku, places=6)
        self.assertAlmostEqual(r.ti, 1.0, places=6)  # Pu/2
        self.assertAlmostEqual(r.kd, r.kp * (2.0 / 8.0), places=6)

    def test_rejects_tiny_amp(self) -> None:
        self.assertIsNone(
            zn_pid_from_relay(relay_amp_hz=8.0, speed_amp_mpm=1e-6, period_s=1.0)
        )


class TestPidAutotunerRelay(unittest.TestCase):
    def test_synthetic_oscillation_completes(self) -> None:
        """Drive a simple plant with the relay; expect DONE with finite coeffs."""
        tuner = PidAutotuner(
            setpoint_mpm=10.0,
            relay_amp_hz=5.0,
            hysteresis_mpm=0.4,
            min_cycles=3,
            timeout_s=30.0,
            ramp_s=0.5,
            bias_hz_per_mpm=1.0,
        )
        # Fake clock so periods are stable
        t = [0.0]

        def fake_mono() -> float:
            return t[0]

        speed = 0.0
        with patch("brakovka_pi.pid_autotune.monotonic", side_effect=fake_mono):
            tuner.start()
            finished = False
            result = None
            for _ in range(5000):
                # Simple 1st-order plant: speed follows freq
                # Use last command from previous step — approximate with bias±amp
                dt = 0.02
                t[0] += dt
                # Open-loop / relay plant: speed += (u - speed)*a
                # Get command by stepping (uses current speed)
                step = tuner.step(speed, dt)
                u = step.freq_hz
                # Plant: tau=0.3s, gain 1 mpm/Hz
                speed += ((u * 1.0) - speed) * min(1.0, dt / 0.3)
                if step.finished:
                    finished = True
                    result = step.result
                    self.assertEqual(step.phase, AutotunePhase.DONE)
                    break

        self.assertTrue(finished, "autotune did not finish in time")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreater(result.kp, 0.0)
        self.assertGreater(result.ti, 0.0)
        self.assertGreaterEqual(result.kd, 0.0)
        self.assertGreater(result.pu_s, 0.1)

    def test_abort(self) -> None:
        tuner = PidAutotuner(setpoint_mpm=10.0)
        tuner.start()
        self.assertEqual(tuner.phase, AutotunePhase.RAMP)
        tuner.abort("СТОП")
        step = tuner.step(0.0, 0.01)
        self.assertTrue(step.finished)
        self.assertEqual(step.phase, AutotunePhase.ABORTED)


class TestMachineAutotuneGate(unittest.TestCase):
    def test_start_only_from_idle(self) -> None:
        from brakovka_pi.machine import Machine
        from brakovka_pi.state import MachineState

        m = Machine()
        self.assertTrue(m.start_autotune())
        self.assertTrue(m.telem.autotune_active)
        self.assertEqual(m.telem.state, MachineState.RUN)
        # Second start rejected while active
        self.assertFalse(m.start_autotune())
        m.abort_autotune("test")
        self.assertFalse(m.telem.autotune_active)


if __name__ == "__main__":
    unittest.main()
