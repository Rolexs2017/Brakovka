"""Unit tests for step-response PID autotune (IMC / PI+feedforward)."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from brakovka_pi.pid_autotune import AutotunePhase
from brakovka_pi.pid_tune import (
    PidTuneMethod,
    StepResponseAutotuner,
    StepSample,
    identify_fopdt_from_step,
    imc_pi_from_fopdt,
    parse_pid_tune_method,
)


class TestPidTuneMethod(unittest.TestCase):
    def test_parse_defaults_to_relay(self) -> None:
        self.assertEqual(parse_pid_tune_method(None), "relay")
        self.assertEqual(parse_pid_tune_method("bogus"), "relay")
        self.assertEqual(parse_pid_tune_method("step_imc"), "step_imc")
        self.assertEqual(parse_pid_tune_method("pi_ff"), "pi_ff")


class TestFopdtIdentify(unittest.TestCase):
    def test_identify_first_order_step(self) -> None:
        # y(t) = K*u*(1-exp(-(t-L)/T)), u=10 Hz, K=0.5 mpm/Hz, T=0.4s, L=0.1s
        k_proc, t_s, l_s = 0.5, 0.4, 0.1
        step_hz = 10.0
        baseline_count = 30
        dt = 0.05
        step_t = baseline_count * dt
        samples: list[StepSample] = []
        t = 0.0
        for _ in range(200):
            u = step_hz if t >= step_t else 0.0
            if u > 0:
                td = t - step_t
                if td >= l_s:
                    y = k_proc * step_hz * (1.0 - math.exp(-(td - l_s) / t_s))
                else:
                    y = 0.0
            else:
                y = 0.0
            samples.append(StepSample(t=t, speed_mpm=y))
            t += dt

        result = identify_fopdt_from_step(samples, step_hz=step_hz, baseline_count=baseline_count, tail_count=30)
        self.assertIsNotNone(result)
        assert result is not None
        k_est, t_est, l_est = result
        self.assertAlmostEqual(k_est, k_proc, delta=0.15)
        self.assertAlmostEqual(t_est, t_s, delta=0.25)
        self.assertAlmostEqual(l_est, l_s, delta=0.15)

    def test_imc_pi_positive(self) -> None:
        raw = imc_pi_from_fopdt(0.5, 0.4, 0.1, lambda_s=1.0)
        self.assertIsNotNone(raw)
        assert raw is not None
        kp, ti, kd = raw
        self.assertGreater(kp, 0.0)
        self.assertGreater(ti, 0.0)
        self.assertEqual(kd, 0.0)


class TestStepResponseAutotuner(unittest.TestCase):
    def test_step_imc_completes_on_synthetic_plant(self) -> None:
        tuner = StepResponseAutotuner(
            mode=PidTuneMethod.STEP_IMC.value,
            step_hz=10.0,
            baseline_s=0.5,
            step_duration_s=3.0,
            timeout_s=20.0,
        )
        t = [0.0]
        speed = 0.0

        def fake_mono() -> float:
            return t[0]

        with patch("brakovka_pi.pid_tune.monotonic", side_effect=fake_mono):
            tuner.start()
            finished = False
            for _ in range(3000):
                dt = 0.02
                t[0] += dt
                step = tuner.step(speed, dt)
                u = step.freq_hz
                speed += ((u * 0.5) - speed) * min(1.0, dt / 0.35)
                if step.finished:
                    finished = True
                    self.assertEqual(step.phase, AutotunePhase.DONE)
                    self.assertIsNotNone(step.result)
                    assert step.result is not None
                    self.assertGreater(step.result.kp, 0.0)
                    self.assertGreater(step.result.ti, 0.0)
                    break

        self.assertTrue(finished)

    def test_pi_ff_sets_mpm_per_hz(self) -> None:
        tuner = StepResponseAutotuner(
            mode=PidTuneMethod.PI_FF.value,
            step_hz=10.0,
            baseline_s=0.5,
            step_duration_s=3.0,
            timeout_s=20.0,
        )
        t = [0.0]
        speed = 0.0

        def fake_mono() -> float:
            return t[0]

        with patch("brakovka_pi.pid_tune.monotonic", side_effect=fake_mono):
            tuner.start()
            result = None
            for _ in range(3000):
                dt = 0.02
                t[0] += dt
                step = tuner.step(speed, dt)
                u = step.freq_hz
                speed += ((u * 0.5) - speed) * min(1.0, dt / 0.35)
                if step.finished:
                    result = step.result
                    break

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNotNone(result.mpm_per_hz)
        self.assertGreater(result.mpm_per_hz or 0.0, 0.0)


if __name__ == "__main__":
    unittest.main()
