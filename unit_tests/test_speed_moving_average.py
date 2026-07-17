"""Unit tests for speed moving average before PID."""

from __future__ import annotations

import unittest

from brakovka_pi.encoder import PID_REGULATOR_SPEED_AVG_N, SpeedMovingAverage


class TestSpeedMovingAverage(unittest.TestCase):
    def test_window_10_mean(self) -> None:
        self.assertEqual(PID_REGULATOR_SPEED_AVG_N, 10)
        filt = SpeedMovingAverage(10)
        for i in range(1, 11):
            v = filt.update(float(i))
        self.assertAlmostEqual(v, 5.5, places=6)

    def test_reset(self) -> None:
        filt = SpeedMovingAverage(10)
        filt.update(100.0)
        filt.reset(0.0)
        self.assertEqual(filt.value_mpm, 0.0)
        self.assertAlmostEqual(filt.update(20.0), 20.0, places=6)


if __name__ == "__main__":
    unittest.main()
