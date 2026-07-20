"""Unit tests for AS5600 I2C debounce gate."""

from __future__ import annotations

import unittest

from brakovka_pi.encoder import EncoderFaultGate, EncoderTelemetry


class TestEncoderFaultGate(unittest.TestCase):
    def test_transient_glitch_ignored(self) -> None:
        gate = EncoderFaultGate(fault_streak=3, recover_streak=2)
        good = EncoderTelemetry(wound_m=1.0, unwind_m=0.5, pulses=10, ok=True)
        out = gate.update(True, good)
        self.assertTrue(out.ok)
        self.assertAlmostEqual(out.wound_m, 1.0)

        bad = EncoderTelemetry(wound_m=1.0, ok=False)
        out = gate.update(False, bad)
        self.assertTrue(out.ok)
        self.assertAlmostEqual(out.wound_m, 1.0)

    def test_latched_fault_after_streak(self) -> None:
        gate = EncoderFaultGate(fault_streak=2, recover_streak=2)
        good = EncoderTelemetry(wound_m=2.0, ok=True)
        gate.update(True, good)
        bad = EncoderTelemetry(ok=False)
        gate.update(False, bad)
        out = gate.update(False, bad)
        self.assertFalse(out.ok)
        self.assertAlmostEqual(out.wound_m, 2.0)

    def test_recovery_requires_streak(self) -> None:
        gate = EncoderFaultGate(fault_streak=2, recover_streak=3)
        good = EncoderTelemetry(wound_m=3.0, ok=True)
        gate.update(True, good)
        bad = EncoderTelemetry(ok=False)
        gate.update(False, bad)
        gate.update(False, bad)
        self.assertTrue(gate.latched_fault)
        gate.update(True, good)
        self.assertTrue(gate.latched_fault)
        gate.update(True, good)
        self.assertTrue(gate.latched_fault)
        out = gate.update(True, good)
        self.assertTrue(out.ok)


if __name__ == "__main__":
    unittest.main()
