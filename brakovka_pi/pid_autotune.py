from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import pi
from time import monotonic


class AutotunePhase(str, Enum):
    IDLE = "idle"
    RAMP = "ramp"
    RELAY = "relay"
    BASELINE = "baseline"
    STEP = "step"
    DONE = "done"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass(frozen=True)
class AutotuneResult:
    kp: float
    ti: float
    kd: float
    ku: float = 0.0
    pu_s: float = 0.0
    amp_mpm: float = 0.0
    mpm_per_hz: float | None = None


@dataclass
class AutotuneStep:
    """One control tick output from the autotuner."""

    freq_hz: float
    run: bool
    phase: AutotunePhase
    message: str = ""
    result: AutotuneResult | None = None
    finished: bool = False


def zn_pid_from_relay(*, relay_amp_hz: float, speed_amp_mpm: float, period_s: float) -> AutotuneResult | None:
    """
    Åström–Hägglund Ku + classic Ziegler–Nichols PID.

    Maps to Pid form: i=(kp/ti)·∫e, d=kd·de/dt
      Kp = 0.6·Ku
      Ti = Pu/2
      Kd = Kp·(Pu/8)
    """
    a = abs(float(speed_amp_mpm))
    d = abs(float(relay_amp_hz))
    pu = float(period_s)
    if a < 1e-4 or d < 1e-6 or pu < 0.05:
        return None
    ku = (4.0 * d) / (pi * a)
    kp = 0.6 * ku
    ti = pu / 2.0
    kd = kp * (pu / 8.0)
    return AutotuneResult(kp=kp, ti=ti, kd=kd, ku=ku, pu_s=pu, amp_mpm=a)


class PidAutotuner:
    """
    Relay autotune for speed → VFD frequency loop.

    Phases:
      RAMP  — open-loop bias to approach setpoint
      RELAY — ±relay_amp_hz around bias with speed hysteresis
      DONE / FAILED / ABORTED
    """

    def __init__(
        self,
        *,
        setpoint_mpm: float,
        relay_amp_hz: float = 8.0,
        hysteresis_mpm: float = 0.3,
        min_cycles: int = 3,
        timeout_s: float = 45.0,
        ramp_s: float = 3.0,
        bias_hz_per_mpm: float = 1.0,
        out_min_hz: float = 0.0,
        out_max_hz: float = 320.0,
        kp_lo: float = 0.0,
        kp_hi: float = 1e6,
        ti_lo: float = 0.0,
        ti_hi: float = 1e6,
        kd_lo: float = 0.0,
        kd_hi: float = 1e6,
    ) -> None:
        self.setpoint_mpm = max(0.1, float(setpoint_mpm))
        self.relay_amp_hz = max(0.5, float(relay_amp_hz))
        self.hysteresis_mpm = max(0.05, float(hysteresis_mpm))
        self.min_cycles = max(2, int(min_cycles))
        self.timeout_s = max(5.0, float(timeout_s))
        self.ramp_s = max(0.5, float(ramp_s))
        self.bias_hz_per_mpm = max(0.05, float(bias_hz_per_mpm))
        self.out_min_hz = float(out_min_hz)
        self.out_max_hz = float(out_max_hz)
        self._kp_lo, self._kp_hi = kp_lo, kp_hi
        self._ti_lo, self._ti_hi = ti_lo, ti_hi
        self._kd_lo, self._kd_hi = kd_lo, kd_hi

        self.phase = AutotunePhase.IDLE
        self.message = ""
        self.result: AutotuneResult | None = None

        self._t0 = 0.0
        self._bias_hz = 0.0
        self._relay_high = True
        self._switch_times: list[float] = []
        self._peaks: list[float] = []
        self._valleys: list[float] = []
        self._extremum = 0.0
        self._looking_peak = True
        self._cycles = 0
        self._last_speed = 0.0

    def start(self) -> None:
        self.phase = AutotunePhase.RAMP
        self.message = "Разгон к уставке"
        self.result = None
        self._t0 = monotonic()
        self._bias_hz = self._clamp_hz(self.setpoint_mpm * self.bias_hz_per_mpm)
        self._relay_high = True
        self._switch_times.clear()
        self._peaks.clear()
        self._valleys.clear()
        self._extremum = 0.0
        self._looking_peak = True
        self._cycles = 0
        self._last_speed = 0.0

    def abort(self, reason: str = "Прервано") -> None:
        if self.phase in (AutotunePhase.DONE, AutotunePhase.FAILED, AutotunePhase.ABORTED, AutotunePhase.IDLE):
            if self.phase == AutotunePhase.IDLE:
                return
        self.phase = AutotunePhase.ABORTED
        self.message = reason

    def step(self, actual_mpm: float, dt_s: float) -> AutotuneStep:
        _ = dt_s
        speed = max(0.0, float(actual_mpm))
        self._last_speed = speed
        now = monotonic()
        elapsed = now - self._t0

        if self.phase in (AutotunePhase.DONE, AutotunePhase.FAILED, AutotunePhase.ABORTED, AutotunePhase.IDLE):
            finished = self.phase != AutotunePhase.IDLE
            return AutotuneStep(
                freq_hz=0.0,
                run=False,
                phase=self.phase,
                message=self.message,
                result=self.result,
                finished=finished,
            )

        if elapsed > self.timeout_s:
            return self._fail("Таймаут автонастройки")

        if self.phase == AutotunePhase.RAMP:
            # Open-loop bias; wait until near setpoint or ramp time elapsed.
            u = self._bias_hz
            near = abs(speed - self.setpoint_mpm) <= max(self.hysteresis_mpm * 2.0, 0.5)
            if near or elapsed >= self.ramp_s:
                self.phase = AutotunePhase.RELAY
                self.message = "Relay-тест"
                self._extremum = speed
                self._looking_peak = True
                self._relay_high = speed < self.setpoint_mpm
            return AutotuneStep(freq_hz=u, run=True, phase=self.phase, message=self.message)

        # RELAY
        err = self.setpoint_mpm - speed
        h = self.hysteresis_mpm
        switched = False
        if self._relay_high and err < -h:
            self._relay_high = False
            switched = True
        elif (not self._relay_high) and err > h:
            self._relay_high = True
            switched = True

        if switched:
            self._switch_times.append(now)
            if self._relay_high:
                # Just went high → previous half-cycle was descending → valley
                self._valleys.append(self._extremum)
            else:
                self._peaks.append(self._extremum)
            self._extremum = speed
            self._looking_peak = self._relay_high
            self._cycles = min(len(self._peaks), len(self._valleys))

        # Track extremum between switches
        if self._looking_peak:
            if speed > self._extremum:
                self._extremum = speed
        else:
            if speed < self._extremum:
                self._extremum = speed

        u = self._bias_hz + (self.relay_amp_hz if self._relay_high else -self.relay_amp_hz)
        u = self._clamp_hz(u)

        # Need min_cycles complete peak-valley pairs and enough switch periods
        if self._cycles >= self.min_cycles and len(self._switch_times) >= (2 * self.min_cycles + 1):
            periods: list[float] = []
            sw = self._switch_times
            for i in range(2, len(sw), 2):
                periods.append(sw[i] - sw[i - 2])
            use = periods[-self.min_cycles :]
            peaks = self._peaks[-self.min_cycles :]
            valleys = self._valleys[-self.min_cycles :]
            if not use or not peaks or not valleys:
                return AutotuneStep(freq_hz=u, run=True, phase=self.phase, message=self.message)
            pu = sum(use) / len(use)
            amp = 0.5 * (sum(peaks) / len(peaks) - sum(valleys) / len(valleys))
            raw = zn_pid_from_relay(
                relay_amp_hz=self.relay_amp_hz,
                speed_amp_mpm=amp,
                period_s=pu,
            )
            if raw is None:
                return self._fail("Слабые колебания (проверьте amp/уставку)")
            clamped = AutotuneResult(
                kp=self._clamp(raw.kp, self._kp_lo, self._kp_hi),
                ti=self._clamp(raw.ti, self._ti_lo, self._ti_hi),
                kd=self._clamp(raw.kd, self._kd_lo, self._kd_hi),
                ku=raw.ku,
                pu_s=raw.pu_s,
                amp_mpm=raw.amp_mpm,
            )
            self.phase = AutotunePhase.DONE
            self.result = clamped
            self.message = (
                f"OK: Kp={clamped.kp:.2f} Ti={clamped.ti:.2f} Kd={clamped.kd:.3f} "
                f"(Ku={clamped.ku:.2f} Pu={clamped.pu_s:.2f}s)"
            )
            return AutotuneStep(
                freq_hz=0.0,
                run=False,
                phase=self.phase,
                message=self.message,
                result=clamped,
                finished=True,
            )

        self.message = f"Relay: циклов {self._cycles}/{self.min_cycles}"
        return AutotuneStep(freq_hz=u, run=True, phase=self.phase, message=self.message)

    def _fail(self, reason: str) -> AutotuneStep:
        self.phase = AutotunePhase.FAILED
        self.message = reason
        self.result = None
        return AutotuneStep(
            freq_hz=0.0,
            run=False,
            phase=self.phase,
            message=self.message,
            finished=True,
        )

    def _clamp_hz(self, hz: float) -> float:
        return max(self.out_min_hz, min(self.out_max_hz, float(hz)))

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(v)))
