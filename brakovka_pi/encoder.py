from __future__ import annotations

from dataclasses import dataclass
from math import fabs, pi

from .as5600 import AS5600_ADDR, STATUS_MD, As5600


@dataclass
class EncoderTelemetry:
    speed_mpm: float = 0.0
    wound_m: float = 0.0
    unwind_m: float = 0.0
    ok: bool = True
    magnet_ok: bool = True


class Encoder:
    def __init__(self, roll_diameter_m: float, spike_threshold_m: float = 2.0) -> None:
        self._as = As5600(bus=1, address=AS5600_ADDR)
        self._prev_raw: int | None = None
        self._unwind_m = 0.0
        self._wound_m = 0.0
        self._roll_diameter_m = roll_diameter_m
        self._spike_m = spike_threshold_m

    def set_roll_diameter_m(self, roll_diameter_m: float) -> None:
        if roll_diameter_m <= 0:
            return
        self._roll_diameter_m = roll_diameter_m

    def reset_unwind(self) -> None:
        """New unwind roll: consumed length = 0 (diameter = start_diameter). Keep wound."""
        self._prev_raw = None
        self._unwind_m = 0.0

    def reset_wound(self) -> None:
        self._wound_m = 0.0

    def close(self) -> None:
        self._as.close()

    def step(self, dt_s: float, forward: bool, wound_enable: bool) -> EncoderTelemetry:
        """
        dt_s: период вызова
        forward: направление (True=вперёд, False=реверс)
        wound_enable: учитывать намотку потребительского ролика
        """
        if dt_s <= 0:
            return EncoderTelemetry(
                speed_mpm=0.0, wound_m=self._wound_m, unwind_m=self._unwind_m, ok=True
            )

        try:
            s = self._as.read()
        except Exception:
            return EncoderTelemetry(
                speed_mpm=0.0,
                wound_m=self._wound_m,
                unwind_m=self._unwind_m,
                ok=False,
                magnet_ok=False,
            )

        magnet_ok = bool(s.status & STATUS_MD)
        raw = int(s.raw) & 0x0FFF
        if self._prev_raw is None:
            self._prev_raw = raw
            return EncoderTelemetry(
                speed_mpm=0.0,
                wound_m=self._wound_m,
                unwind_m=self._unwind_m,
                ok=True,
                magnet_ok=magnet_ok,
            )

        delta = raw - self._prev_raw
        self._prev_raw = raw

        # unwrap for 12-bit angle
        if delta > 2048:
            delta -= 4096
        elif delta < -2048:
            delta += 4096

        rev = delta / 4096.0
        circumference = pi * self._roll_diameter_m
        delta_m = rev * circumference
        if not forward:
            delta_m = -delta_m

        ok = True
        if fabs(delta_m) > self._spike_m:
            # spike / I2C glitch
            delta_m = 0.0
            ok = False

        self._unwind_m += delta_m
        if self._unwind_m < 0:
            self._unwind_m = 0.0

        if wound_enable and ok and delta_m > 0:
            self._wound_m += delta_m

        speed_mpm = (delta_m / dt_s) * 60.0
        return EncoderTelemetry(
            speed_mpm=speed_mpm,
            wound_m=self._wound_m,
            unwind_m=self._unwind_m,
            ok=ok,
            magnet_ok=magnet_ok,
        )
