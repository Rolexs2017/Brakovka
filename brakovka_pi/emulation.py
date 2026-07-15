from __future__ import annotations

from math import pi

from .modbus_rs485 import VfdCommand
from .encoder import SpeedMedianFilter
from .roll_geometry import wound_diameter_m


class EmulatedVfd:
    """
    Виртуальный частотник.

    Хранит последнюю команду (run/reverse/freq_hz) и выдаёт статусное слово в стиле ПЧВ‑3:
    bit0 running, bit1 accel, bit2 decel, bit3 reverse, bit4 fault, bit6 warning, bit7 start_possible.
    """

    def __init__(self) -> None:
        self.run = False
        self.reverse = False
        self.freq_cmd_hz = 0.0

    @property
    def connected(self) -> bool:
        return True

    async def connect(self) -> None:
        return

    async def close(self) -> None:
        return

    async def reconnect(self, *, force: bool = False) -> bool:
        _ = force
        return True

    async def write_command(self, cmd: VfdCommand) -> bool:
        self.run = bool(cmd.run)
        self.reverse = bool(cmd.reverse)
        self.freq_cmd_hz = max(0.0, float(cmd.speed_setpoint_hz))
        return True

    async def read_status(self) -> dict:
        sw = 0
        if self.run and self.freq_cmd_hz > 0.01:
            sw |= 1 << 0  # running
        if self.reverse:
            sw |= 1 << 3
        sw |= 1 << 7  # start_possible
        return {
            "status_word": sw,
            "error_code": 0,
            "freq_out_hz": self.freq_cmd_hz,
            "fault": False,
            "warning": False,
        }


class SimEncoder:
    """
    Виртуальный энкодер: Hz → rpm → линейная скорость с учётом диаметра потребителя,
    инерция 1-го порядка + медианный фильтр (как на железе).
    """

    def __init__(
        self,
        tau_s: float = 0.15,
        gear_ratio: float = 20.0,
        motor_rpm_per_hz: float = 60.0,
        consumer_core_diameter_m: float = 0.076,
        thickness_m: float = 0.0003,
        roll_diameter_m: float = 0.08,
        speed_filter_n: int = 5,
    ) -> None:
        self.tau_s = max(0.01, float(tau_s))
        # Allow ratios < 1 (e.g. 0.2): motor rpm / gear → roller rpm.
        self.gear_ratio = max(1e-6, float(gear_ratio))
        self.motor_rpm_per_hz = max(0.01, float(motor_rpm_per_hz))
        self.consumer_core_diameter_m = max(0.001, float(consumer_core_diameter_m))
        self.thickness_m = max(1e-6, float(thickness_m))
        self.roll_diameter_m = max(0.001, float(roll_diameter_m))

        self._speed_mpm = 0.0
        self._unwind_pulses = 0
        self._wound_pulses = 0
        self._speed_filt = SpeedMedianFilter(speed_filter_n)
        self._consumer_diameter_m = self.consumer_core_diameter_m

    def set_speed_filter_n(self, window: int) -> None:
        self._speed_filt.set_window(window)

    def _meters_per_count(self) -> float:
        return (pi * self.roll_diameter_m) / 4096.0

    def _length_m(self, pulses: int) -> float:
        return max(0.0, float(pulses) * self._meters_per_count())

    def reset_unwind(self) -> None:
        """New unwind roll loaded: consumed length = 0. Keep consumer wound/diameter."""
        self._unwind_pulses = 0

    def reset_wound(self) -> None:
        self._wound_pulses = 0
        self._consumer_diameter_m = self.consumer_core_diameter_m

    def step(self, dt_s: float, freq_cmd_hz: float, forward: bool, wound_enable: bool) -> dict:
        motor_rpm = max(0.0, float(freq_cmd_hz)) * self.motor_rpm_per_hz
        roller_rpm = motor_rpm / self.gear_ratio
        target_mpm = (roller_rpm * (pi * self._consumer_diameter_m)) / 60.0

        a = min(1.0, dt_s / self.tau_s)
        self._speed_mpm += (target_mpm - self._speed_mpm) * a

        delta_m = (self._speed_mpm / 60.0) * dt_s
        if not forward:
            delta_m = -delta_m

        mpc = self._meters_per_count()
        signed = int(round(delta_m / mpc)) if mpc > 1e-12 else 0
        self._unwind_pulses = max(0, self._unwind_pulses + signed)
        if wound_enable:
            self._wound_pulses = max(0, self._wound_pulses + signed)

        wound_m = self._length_m(self._wound_pulses)
        unwind_m = self._length_m(self._unwind_pulses)
        self._consumer_diameter_m = wound_diameter_m(
            self.consumer_core_diameter_m,
            self.thickness_m,
            wound_m,
        )

        return {
            "speed_mpm": self._speed_filt.update(self._speed_mpm),
            "wound_m": wound_m,
            "unwind_m": unwind_m,
            "pulses": self._wound_pulses,
            "consumer_diameter_mm": self._consumer_diameter_m * 1000.0,
            "ok": True,
        }
