from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import monotonic

from .pid_autotune import AutotunePhase, AutotuneResult, AutotuneStep


class PidTuneMethod(str, Enum):
    RELAY = "relay"
    STEP_IMC = "step_imc"
    PI_FF = "pi_ff"


PID_TUNE_METHOD_LABELS: dict[str, str] = {
    PidTuneMethod.RELAY.value: "Relay (Ziegler–Nichols)",
    PidTuneMethod.STEP_IMC.value: "Ступенька + IMC",
    PidTuneMethod.PI_FF.value: "PI + feedforward",
}

PID_TUNE_METHOD_HINTS: dict[str, str] = {
    PidTuneMethod.RELAY.value: (
        "Колебания частоты ПЧ (relay), расчёт Ku/Pu и Ziegler–Nichols. Рабочий режим — классический PID."
    ),
    PidTuneMethod.STEP_IMC.value: (
        "Открытая ступенька частоты, идентификация FOPDT, коэффициенты IMC. Рабочий режим — классический PID."
    ),
    PidTuneMethod.PI_FF.value: (
        "Калибровка feedforward (м/мин)/Гц и небольшой PI. Рабочий режим: freq = setpoint/FF + PI."
    ),
}

PID_TUNE_METHOD_ORDER: tuple[str, ...] = (
    PidTuneMethod.RELAY.value,
    PidTuneMethod.STEP_IMC.value,
    PidTuneMethod.PI_FF.value,
)


def parse_pid_tune_method(raw: object) -> str:
    v = str(raw or PidTuneMethod.RELAY.value).strip().lower()
    if v in {m.value for m in PidTuneMethod}:
        return v
    return PidTuneMethod.RELAY.value


@dataclass(frozen=True)
class StepSample:
    t: float
    speed_mpm: float


def identify_fopdt_from_step(
    samples: list[StepSample],
    *,
    step_hz: float,
    baseline_count: int = 20,
    tail_count: int = 30,
) -> tuple[float, float, float] | None:
    """
    Identify FOPDT from open-loop step response.

    Returns (K_mpm_per_hz, T_s, L_s) or None.
    """
    if len(samples) < baseline_count + tail_count + 5:
        return None
    step_hz = abs(float(step_hz))
    if step_hz < 0.1:
        return None

    baseline = [s.speed_mpm for s in samples[:baseline_count]]
    y0 = sum(baseline) / len(baseline)

    tail = [s.speed_mpm for s in samples[-tail_count:]]
    y_inf = sum(tail) / len(tail)
    dy = y_inf - y0
    if abs(dy) < 0.05:
        return None

    k_proc = dy / step_hz

    thresh_lo = y0 + 0.1 * abs(dy)
    t0 = samples[baseline_count - 1].t
    l_s = 0.0
    found_l = False
    for s in samples[baseline_count:]:
        if (dy > 0 and s.speed_mpm >= thresh_lo) or (dy < 0 and s.speed_mpm <= thresh_lo):
            l_s = max(0.0, s.t - t0)
            found_l = True
            break
    if not found_l:
        l_s = 0.05

    target = y0 + 0.632 * dy
    t_step = samples[baseline_count].t
    t_s: float | None = None
    for s in samples[baseline_count:]:
        if s.t < t_step + l_s:
            continue
        if (dy > 0 and s.speed_mpm >= target) or (dy < 0 and s.speed_mpm <= target):
            t_s = max(0.05, s.t - t_step - l_s)
            break
    if t_s is None:
        t_s = max(0.1, (samples[-1].t - t_step - l_s) * 0.5)

    return k_proc, t_s, l_s


def imc_pi_from_fopdt(
    k_mpm_per_hz: float,
    t_s: float,
    l_s: float,
    *,
    lambda_s: float = 1.0,
) -> tuple[float, float, float] | None:
    """IMC PI for speed (mpm) → Hz loop. Returns (kp, ti, kd=0)."""
    k_proc = abs(float(k_mpm_per_hz))
    t_val = max(0.05, float(t_s))
    l_val = max(0.0, float(l_s))
    lam = max(0.2, float(lambda_s))
    if k_proc < 1e-4:
        return None
    kp = (t_val + 0.5 * l_val) / (k_proc * lam)
    ti = t_val + 0.5 * l_val
    return kp, ti, 0.0


def pi_ff_gains_from_fopdt(k_mpm_per_hz: float, t_s: float) -> tuple[float, float]:
    """Conservative PI correction gains after feedforward calibration."""
    k_proc = max(0.01, abs(float(k_mpm_per_hz)))
    t_val = max(0.1, float(t_s))
    kp = 0.25 / k_proc
    ti = max(1.0, 2.0 * t_val)
    return kp, ti


class StepResponseAutotuner:
    """
    Open-loop step test → FOPDT identification.

    Modes:
      step_imc — IMC PI coefficients (classic PID runtime)
      pi_ff    — calibrate mpm_per_hz + small PI correction (PI+FF runtime)
    """

    def __init__(
        self,
        *,
        mode: str,
        step_hz: float = 12.0,
        baseline_s: float = 2.0,
        step_duration_s: float = 10.0,
        timeout_s: float = 40.0,
        out_min_hz: float = 0.0,
        out_max_hz: float = 320.0,
        kp_lo: float = 0.0,
        kp_hi: float = 1e6,
        ti_lo: float = 0.0,
        ti_hi: float = 1e6,
        kd_lo: float = 0.0,
        kd_hi: float = 1e6,
        lambda_s: float = 1.0,
    ) -> None:
        self.mode = parse_pid_tune_method(mode)
        if self.mode == PidTuneMethod.RELAY.value:
            self.mode = PidTuneMethod.STEP_IMC.value
        self.step_hz = max(1.0, float(step_hz))
        self.baseline_s = max(0.5, float(baseline_s))
        self.step_duration_s = max(3.0, float(step_duration_s))
        self.timeout_s = max(10.0, float(timeout_s))
        self.out_min_hz = float(out_min_hz)
        self.out_max_hz = float(out_max_hz)
        self._kp_lo, self._kp_hi = kp_lo, kp_hi
        self._ti_lo, self._ti_hi = ti_lo, ti_hi
        self._kd_lo, self._kd_hi = kd_lo, kd_hi
        self.lambda_s = max(0.2, float(lambda_s))

        self.phase = AutotunePhase.IDLE
        self.message = ""
        self.result: AutotuneResult | None = None

        self._t0 = 0.0
        self._phase_t0 = 0.0
        self._samples: list[StepSample] = []

    def start(self) -> None:
        self.phase = AutotunePhase.BASELINE
        self.message = "Базовая линия (0 Гц)"
        self.result = None
        now = monotonic()
        self._t0 = now
        self._phase_t0 = now
        self._samples.clear()

    def abort(self, reason: str = "Прервано") -> None:
        if self.phase in (AutotunePhase.DONE, AutotunePhase.FAILED, AutotunePhase.ABORTED, AutotunePhase.IDLE):
            if self.phase == AutotunePhase.IDLE:
                return
        self.phase = AutotunePhase.ABORTED
        self.message = reason

    def step(self, actual_mpm: float, dt_s: float) -> AutotuneStep:
        _ = dt_s
        speed = max(0.0, float(actual_mpm))
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

        self._samples.append(StepSample(t=now, speed_mpm=speed))
        phase_elapsed = now - self._phase_t0

        if self.phase == AutotunePhase.BASELINE:
            u = 0.0
            if phase_elapsed >= self.baseline_s:
                self.phase = AutotunePhase.STEP
                self._phase_t0 = now
                self.message = f"Ступенька {self.step_hz:.1f} Гц"
            return AutotuneStep(freq_hz=u, run=True, phase=self.phase, message=self.message)

        if self.phase == AutotunePhase.STEP:
            u = self._clamp_hz(self.step_hz)
            if phase_elapsed >= self.step_duration_s:
                return self._analyze()
            self.message = f"Ступенька {self.step_hz:.1f} Гц ({phase_elapsed:.0f}/{self.step_duration_s:.0f} с)"
            return AutotuneStep(freq_hz=u, run=True, phase=self.phase, message=self.message)

        return self._fail("Неизвестная фаза")

    def _analyze(self) -> AutotuneStep:
        fopdt = identify_fopdt_from_step(self._samples, step_hz=self.step_hz)
        if fopdt is None:
            return self._fail("Слабый отклик на ступеньку (проверьте JOG/материал)")
        k_proc, t_s, l_s = fopdt

        mpm_per_hz: float | None = None
        if self.mode == PidTuneMethod.PI_FF.value:
            kp, ti = pi_ff_gains_from_fopdt(k_proc, t_s)
            kd = 0.0
            mpm_per_hz = k_proc
            msg_extra = f" FF={k_proc:.3f} (м/мин)/Гц"
        else:
            raw = imc_pi_from_fopdt(k_proc, t_s, l_s, lambda_s=self.lambda_s)
            if raw is None:
                return self._fail("IMC: не удалось рассчитать коэффициенты")
            kp, ti, kd = raw
            msg_extra = f" K={k_proc:.3f} T={t_s:.2f}s L={l_s:.2f}s"

        clamped = AutotuneResult(
            kp=self._clamp(kp, self._kp_lo, self._kp_hi),
            ti=self._clamp(ti, self._ti_lo, self._ti_hi),
            kd=self._clamp(kd, self._kd_lo, self._kd_hi),
            ku=0.0,
            pu_s=0.0,
            amp_mpm=0.0,
            mpm_per_hz=mpm_per_hz,
        )
        self.phase = AutotunePhase.DONE
        self.result = clamped
        self.message = (
            f"OK: Kp={clamped.kp:.2f} Ti={clamped.ti:.2f} Kd={clamped.kd:.3f}{msg_extra}"
        )
        return AutotuneStep(
            freq_hz=0.0,
            run=False,
            phase=self.phase,
            message=self.message,
            result=clamped,
            finished=True,
        )

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
