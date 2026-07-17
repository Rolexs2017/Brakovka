"""Unit tests for length-window speed and median filter."""

from __future__ import annotations

import unittest

from brakovka_pi.encoder import (
    PID_REGULATOR_SPEED_MEDIAN_N,
    SPEED_LENGTH_WINDOW_S,
    SpeedFromLengthWindow,
    SpeedMedianFilter,
)


class TestSpeedFromLengthWindow(unittest.TestCase):
    def test_constant_speed(self) -> None:
        self.assertAlmostEqual(SPEED_LENGTH_WINDOW_S, 0.1, places=6)
        win = SpeedFromLengthWindow(0.1)
        # 1 m over 1 s → 60 m/min; feed samples spanning 0.1 s at same rate
        for i in range(11):
            t = i * 0.01
            v = win.update(wound_m=t * 1.0, now_s=t)  # 1 m/s
        self.assertAlmostEqual(v, 60.0, places=4)

    def test_reset(self) -> None:
        win = SpeedFromLengthWindow(0.1)
        win.update(1.0, 1.0)
        win.reset(0.0)
        self.assertEqual(win.value_mpm, 0.0)
        self.assertAlmostEqual(win.update(0.0, 2.0), 0.0, places=6)


class TestSpeedMedianFilter(unittest.TestCase):
    def test_odd_window_median(self) -> None:
        self.assertEqual(PID_REGULATOR_SPEED_MEDIAN_N, 11)
        filt = SpeedMedianFilter(5)
        for x in (1.0, 100.0, 2.0, 3.0, 4.0):
            v = filt.update(x)
        # buffer: 1,100,2,3,4 → sorted 1,2,3,4,100 → median 3
        self.assertAlmostEqual(v, 3.0, places=6)

    def test_even_window_becomes_odd(self) -> None:
        filt = SpeedMedianFilter(4)
        self.assertEqual(filt._window, 5)

    def test_rejects_spike_in_window(self) -> None:
        filt = SpeedMedianFilter(5)
        for x in (50.0, 50.0, 50.0, 50.0, 500.0):
            v = filt.update(x)
        self.assertAlmostEqual(v, 50.0, places=6)

    def test_reset(self) -> None:
        filt = SpeedMedianFilter(5)
        filt.update(100.0)
        filt.reset(0.0)
        self.assertEqual(filt.value_mpm, 0.0)
        self.assertAlmostEqual(filt.update(20.0), 20.0, places=6)


if __name__ == "__main__":
    unittest.main()
