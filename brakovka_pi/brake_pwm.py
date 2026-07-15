from __future__ import annotations

try:
    from gpiozero import PWMOutputDevice  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    PWMOutputDevice = None

from .config import GpioConfig


class BrakePwm:
    def __init__(self, gpio: GpioConfig | None = None) -> None:
        gpio = gpio or GpioConfig()
        # gpiozero pin factory is set by run_brakovka / GPIOZERO_PIN_FACTORY (lgpio on Trixie).
        self._pwm = None
        if PWMOutputDevice is not None:
            try:
                self._pwm = PWMOutputDevice(gpio.brake_pwm, frequency=1000, initial_value=0.0)
            except Exception:
                self._pwm = None

    def set_pressure_pct(self, pct: float) -> None:
        if self._pwm is None:
            return
        if pct < 0.0:
            pct = 0.0
        if pct > 100.0:
            pct = 100.0
        self._pwm.value = pct / 100.0

    def off(self) -> None:
        self.set_pressure_pct(0.0)

    def close(self) -> None:
        self.off()
        if self._pwm is not None:
            try:
                self._pwm.close()
            except Exception:
                pass
            self._pwm = None
