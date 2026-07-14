from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pid:
    """
    Simple PID with optional derivative and anti-windup back-calculation.

    kp: output / error
    ti: seconds, 0 disables integral
    kd: output * seconds / error, 0 disables derivative
    """

    kp: float
    ti: float = 0.0
    kd: float = 0.0
    out_min: float | None = None
    out_max: float | None = None

    _i: float = 0.0
    _prev_err: float = 0.0

    def reset(self) -> None:
        self._i = 0.0
        self._prev_err = 0.0

    def step(self, err: float, dt_s: float) -> float:
        if dt_s <= 0:
            return 0.0

        p = self.kp * err

        d = 0.0
        if self.kd > 1e-12:
            d = self.kd * (err - self._prev_err) / dt_s
        self._prev_err = err

        i_term = 0.0
        if self.ti > 1e-12:
            self._i += err * dt_s
            i_term = (self.kp / self.ti) * self._i

        out = p + i_term + d
        out_unsat = out

        if self.out_min is not None and out < self.out_min:
            out = self.out_min
        if self.out_max is not None and out > self.out_max:
            out = self.out_max

        # Anti-windup: if saturated, back-calculate integral to match the saturated output.
        if out != out_unsat and self.ti > 1e-12:
            remaining = out - (p + d)
            if abs(self.kp) > 1e-12:
                self._i = remaining * self.ti / self.kp
            else:
                self._i = 0.0

        return float(out)

