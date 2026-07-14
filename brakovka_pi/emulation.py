from __future__ import annotations

from math import pi

from .modbus_rs485 import VfdCommand
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

    async def ensure_connected(self) -> bool:
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
    Виртуальный энкодер: скорость реагирует на команду частоты частотника с 1‑порядковым фильтром.

    ВАЖНО: для настройки PID "частота -> скорость" полезно учитывать рост диаметра потребительского рулона:
    при постоянной угловой скорости линейная скорость растёт с диаметром.
    """

    def __init__(
        self,
        mpm_per_hz: float = 1.0,
        tau_s: float = 0.15,
        gear_ratio: float = 20.0,
        motor_rpm_per_hz: float = 60.0,
        consumer_core_diameter_m: float = 0.076,
        thickness_m: float = 0.0003,
    ) -> None:
        self.mpm_per_hz = float(mpm_per_hz)
        self.tau_s = max(0.01, float(tau_s))
        self.gear_ratio = max(1.0, float(gear_ratio))
        self.motor_rpm_per_hz = max(0.01, float(motor_rpm_per_hz))
        self.consumer_core_diameter_m = max(0.001, float(consumer_core_diameter_m))
        self.thickness_m = max(1e-6, float(thickness_m))

        self._speed_mpm = 0.0
        self._wound_m = 0.0
        self._unwind_m = 0.0
        self._consumer_diameter_m = self.consumer_core_diameter_m

    def reset_unwind(self) -> None:
        """New unwind roll loaded: consumed length = 0. Keep consumer wound/diameter."""
        self._unwind_m = 0.0

    def reset_wound(self) -> None:
        self._wound_m = 0.0
        # Consumer diameter returns to core diameter baseline
        self._consumer_diameter_m = self.consumer_core_diameter_m

    def step(self, dt_s: float, freq_cmd_hz: float, forward: bool, wound_enable: bool) -> dict:
        # Модель 1 (простая): mpm = Hz * mpm_per_hz
        target_mpm_simple = max(0.0, float(freq_cmd_hz)) * self.mpm_per_hz

        # Модель 2 (механическая): Hz -> motor rpm -> roller rpm (/gear) -> linear speed (depends on diameter)
        motor_rpm = max(0.0, float(freq_cmd_hz)) * self.motor_rpm_per_hz
        roller_rpm = motor_rpm / self.gear_ratio
        target_mpm_mech = (roller_rpm * (pi * self._consumer_diameter_m)) / 60.0

        # Используем механическую модель, но если диаметр ещё не задан/нулевой — fallback на простую
        target_mpm = target_mpm_mech if self._consumer_diameter_m > 1e-6 else target_mpm_simple

        # first order response
        a = dt_s / self.tau_s
        if a > 1.0:
            a = 1.0
        self._speed_mpm += (target_mpm - self._speed_mpm) * a

        delta_m = (self._speed_mpm / 60.0) * dt_s
        if not forward:
            delta_m = -delta_m

        self._unwind_m += delta_m
        if self._unwind_m < 0:
            self._unwind_m = 0.0

        if wound_enable and delta_m > 0:
            self._wound_m += delta_m
            self._consumer_diameter_m = wound_diameter_m(
                self.consumer_core_diameter_m,
                self.thickness_m,
                self._wound_m,
            )

        return {
            "speed_mpm": self._speed_mpm,
            "wound_m": self._wound_m,
            "unwind_m": self._unwind_m,
            "consumer_diameter_mm": self._consumer_diameter_m * 1000.0,
            "ok": True,
        }

