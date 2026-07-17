"""Unit tests for speed outlier rejection before moving average."""

from __future__ import annotations

import unittest

from brakovka_pi.encoder import SpeedOutlierReject


class TestSpeedOutlierReject(unittest.TestCase):
    def test_accepts_normal_ramp(self) -> None:
        filt = SpeedOutlierReject(max_mpm=300.0)
        self.assertAlmostEqual(filt.update(0.0), 0.0, places=6)
        self.assertAlmostEqual(filt.update(10.0), 10.0, places=6)
        self.assertAlmostEqual(filt.update(20.0), 20.0, places=6)

    def test_rejects_upward_spike(self) -> None:
        filt = SpeedOutlierReject(max_mpm=300.0)
        filt.update(50.0)
        self.assertAlmostEqual(filt.update(200.0), 50.0, places=6)

    def test_accepts_downward_step(self) -> None:
        filt = SpeedOutlierReject(max_mpm=300.0)
        filt.update(100.0)
        self.assertAlmostEqual(filt.update(0.0), 0.0, places=6)

    def test_rejects_absolute_overspeed(self) -> None:
        filt = SpeedOutlierReject(max_mpm=100.0)
        filt.update(80.0)
        self.assertAlmostEqual(filt.update(200.0), 80.0, places=6)

    def test_reset(self) -> None:
        filt = SpeedOutlierReject(max_mpm=300.0)
        filt.update(100.0)
        filt.reset(0.0)
        self.assertAlmostEqual(filt.update(15.0), 15.0, places=6)


if __name__ == "__main__":
    unittest.main()
