"""Unit tests for speed from length delta."""

from __future__ import annotations

import unittest

from brakovka_pi.encoder import speed_mpm_from_length_delta


class TestSpeedFromLength(unittest.TestCase):
    def test_one_meter_per_second(self) -> None:
        # 1 m in 1 s → 60 m/min
        self.assertAlmostEqual(speed_mpm_from_length_delta(1.0, 1.0), 60.0, places=6)

    def test_negative_delta_uses_abs(self) -> None:
        self.assertAlmostEqual(speed_mpm_from_length_delta(-0.5, 0.5), 60.0, places=6)

    def test_zero_dt(self) -> None:
        self.assertEqual(speed_mpm_from_length_delta(1.0, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
