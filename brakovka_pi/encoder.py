from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from math import fabs, pi
import logging
import threading
from time import monotonic

from .as5600 import AS5600_ADDR, STATUS_MD, As5600

# AS5600 raw counts per full revolution of the measuring roller.
COUNTS_PER_REV = 4096

log = logging.getLogger(__name__)


def calibrated_roll_diameter_m(true_length_m: float, pulses: int) -> float | None:
    """
    Диаметр мерного ролика по факту: L = N · π · D / 4096
    → D = L · 4096 / (π · N)
    """
    if pulses <= 0 or true_length_m <= 0.0:
        return None
    return (float(true_length_m) * float(COUNTS_PER_REV)) / (pi * float(pulses))


def speed_mpm_from_length_delta(delta_m: float, dt_s: float) -> float:
    """Web speed (m/min) from measuring-roller length change over dt_s."""
    if dt_s <= 1e-6:
        return 0.0
    return (fabs(float(delta_m)) / dt_s) * 60.0


@dataclass
class EncoderTelemetry:
    """Snapshot from encoder thread (speed is computed in the controller loop)."""

    wound_m: float = 0.0
    unwind_m: float = 0.0
    pulses: int = 0
    ok: bool = True
    magnet_ok: bool = True


class SpeedOutlierReject:
    """
    Drop upward speed spikes before averaging/PID.

    Rejects samples above max_mpm × OVERSPEED_FACTOR and sudden upward jumps
    vs the last accepted value. Downward steps (stop/decel) are always accepted.
    On reject, returns the last accepted speed (hold).
    """

    OVERSPEED_FACTOR = 1.5

    def __init__(
        self,
        max_mpm: float = 300.0,
        *,
        max_delta_mpm: float = 40.0,
        spike_ratio: float = 0.85,
        min_ref_mpm: float = 5.0,
    ) -> None:
        self._max_mpm = max(1.0, float(max_mpm))
        self._max_delta_mpm = max(1.0, float(max_delta_mpm))
        self._spike_ratio = max(0.0, float(spike_ratio))
        self._min_ref_mpm = max(0.0, float(min_ref_mpm))
        self._last_mpm = 0.0
        self._primed = False

    def set_max_mpm(self, max_mpm: float) -> None:
        self._max_mpm = max(1.0, float(max_mpm))

    def reset(self, value_mpm: float = 0.0) -> None:
        self._last_mpm = max(0.0, float(value_mpm))
        self._primed = False

    def update(self, raw_mpm: float) -> float:
        raw = max(0.0, float(raw_mpm))
        if raw > self._max_mpm * self.OVERSPEED_FACTOR:
            return self._last_mpm if self._primed else 0.0

        if (
            self._primed
            and self._last_mpm >= self._min_ref_mpm
            and raw > self._last_mpm + max(
                self._max_delta_mpm, self._last_mpm * self._spike_ratio
            )
        ):
            return self._last_mpm

        self._primed = True
        self._last_mpm = raw
        return raw


class SpeedFromLengthWindow:
    """
    Web speed (m/min) from wound length change over a sliding time window.

    Longer Δt reduces AS5600 quantization noise vs one controller period.
    """

    def __init__(self, window_s: float = 0.1) -> None:
        self._window_s = max(0.02, float(window_s))
        self._samples: deque[tuple[float, float]] = deque()  # (t, wound_m)
        self.value_mpm = 0.0

    def reset(self, value_mpm: float = 0.0) -> None:
        self._samples.clear()
        self.value_mpm = max(0.0, float(value_mpm))

    def update(self, wound_m: float, now_s: float) -> float:
        t = float(now_s)
        m = float(wound_m)
        self._samples.append((t, m))
        cutoff = t - self._window_s
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()
        if len(self._samples) < 2:
            return self.value_mpm
        t0, m0 = self._samples[0]
        dt = t - t0
        if dt < 1e-3:
            return self.value_mpm
        self.value_mpm = speed_mpm_from_length_delta(m - m0, dt)
        return self.value_mpm


class SpeedMedianFilter:
    """Median over the last N speed samples (odd window). N<=1 disables."""

    def __init__(self, window: int = 11) -> None:
        n = max(1, int(window))
        if n > 1 and n % 2 == 0:
            n += 1
        self._window = n
        self._buf: deque[float] = deque(maxlen=self._window)
        self.value_mpm = 0.0

    def reset(self, value_mpm: float = 0.0) -> None:
        self._buf.clear()
        self.value_mpm = max(0.0, float(value_mpm))

    def update(self, raw_mpm: float) -> float:
        raw = max(0.0, float(raw_mpm))
        if self._window <= 1:
            self.value_mpm = raw
            return self.value_mpm
        self._buf.append(raw)
        ordered = sorted(self._buf)
        self.value_mpm = ordered[len(ordered) // 2]
        return self.value_mpm


class SpeedDisplayFilter:
    """
    Extra 1st-order low-pass for HMI / OPC telemetry only.

    Does not feed PID — keeps regulator responsive while the on-screen
    speed value is heavily smoothed.
    """

    def __init__(self, tau_s: float = 0.5) -> None:
        self._tau_s = max(0.05, float(tau_s))
        self.value_mpm = 0.0
        self._primed = False

    def reset(self, value_mpm: float = 0.0) -> None:
        self.value_mpm = max(0.0, float(value_mpm))
        self._primed = False

    def update(self, raw_mpm: float, dt_s: float) -> float:
        raw = max(0.0, float(raw_mpm))
        if not self._primed:
            self._primed = True
            self.value_mpm = raw
            return self.value_mpm
        dt = max(1e-4, min(float(dt_s), 0.5))
        alpha = dt / (self._tau_s + dt)
        self.value_mpm += (raw - self.value_mpm) * alpha
        return self.value_mpm


# Length window for ΔL/Δt, then median before PID; display EMA for HMI.
SPEED_LENGTH_WINDOW_S = 0.1
PID_REGULATOR_SPEED_MEDIAN_N = 11
SPEED_DISPLAY_TAU_S = 0.5


class Encoder:
    def __init__(
        self,
        roll_diameter_m: float,
        spike_threshold_m: float = 2.0,
        max_speed_mpm: float = 300.0,
        invert: bool = False,
    ) -> None:
        self._as = As5600(bus=1, address=AS5600_ADDR)
        self._prev_raw: int | None = None
        self._unwind_pulses = 0
        self._wound_pulses = 0
        self._roll_diameter_m = roll_diameter_m
        self._spike_m = spike_threshold_m
        self._max_speed_mpm = max(1.0, float(max_speed_mpm))
        self._invert = bool(invert)

    def set_roll_diameter_m(self, roll_diameter_m: float) -> None:
        if roll_diameter_m <= 0:
            return
        self._roll_diameter_m = roll_diameter_m

    def set_max_speed_mpm(self, max_speed_mpm: float) -> None:
        self._max_speed_mpm = max(1.0, float(max_speed_mpm))

    def set_invert(self, invert: bool) -> None:
        self._invert = bool(invert)

    def reset_unwind(self) -> None:
        """New unwind roll: consumed length = 0 (diameter = start_diameter). Keep wound."""
        self._prev_raw = None
        self._unwind_pulses = 0

    def reset_wound(self) -> None:
        """Reset consumer meterage and its pulse counter together."""
        self._wound_pulses = 0

    def close(self) -> None:
        self._as.close()

    def _meters_per_count(self) -> float:
        return (pi * self._roll_diameter_m) / float(COUNTS_PER_REV)

    def _length_m(self, pulses: int) -> float:
        return max(0.0, float(pulses) * self._meters_per_count())

    def _max_counts_per_step(self, dt_s: float) -> int:
        """Reject I2C/unwrap glitches above plausible web speed."""
        mpc = self._meters_per_count()
        if mpc <= 1e-12 or dt_s <= 0:
            return COUNTS_PER_REV
        max_m = (self._max_speed_mpm / 60.0) * dt_s * 1.5
        return max(1, int(max_m / mpc) + 1)

    def _telem(self, *, ok: bool, magnet_ok: bool = True) -> EncoderTelemetry:
        return EncoderTelemetry(
            wound_m=self._length_m(self._wound_pulses),
            unwind_m=self._length_m(self._unwind_pulses),
            pulses=self._wound_pulses,
            ok=ok,
            magnet_ok=magnet_ok,
        )

    def poll(self, dt_s: float, *, wound_enable: bool = True) -> EncoderTelemetry:
        """
        One AS5600 sample: unwrap angle → pulses → meterage.

        Speed is **not** calculated here; the controller derives it from wound_m.
        """
        if dt_s <= 0:
            return self._telem(ok=True)

        try:
            s = self._as.read()
        except Exception:
            return self._telem(ok=False, magnet_ok=False)

        magnet_ok = bool(s.status & STATUS_MD)
        raw = int(s.raw) & 0x0FFF
        if self._prev_raw is None:
            self._prev_raw = raw
            return self._telem(ok=True, magnet_ok=magnet_ok)

        delta = raw - self._prev_raw
        self._prev_raw = raw

        # unwrap for 12-bit angle
        if delta > 2048:
            delta -= 4096
        elif delta < -2048:
            delta += 4096

        signed = -int(delta) if self._invert else int(delta)
        mpc = self._meters_per_count()
        delta_m = float(signed) * mpc

        max_counts = self._max_counts_per_step(dt_s)
        if fabs(delta_m) > self._spike_m or abs(signed) > max_counts:
            signed = 0

        if signed != 0:
            self._unwind_pulses = max(0, self._unwind_pulses + signed)
            if wound_enable:
                self._wound_pulses = max(0, self._wound_pulses + signed)

        return self._telem(ok=True, magnet_ok=magnet_ok)


class ThreadedEncoder:
    """
    Dedicated thread: AS5600 I2C polling at the maximum sustainable rate.

    Accumulates pulses and meterage only; speed is derived in the controller task.
    """

    def __init__(self, encoder: Encoder) -> None:
        self._enc = encoder
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._telem = EncoderTelemetry()
        self._pending_reset_wound = False
        self._pending_reset_unwind = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="brakovka-encoder",
            daemon=True,
        )
        self._thread.start()
        log.info("Encoder thread started (max I2C poll rate)")

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=timeout_s)
        self._thread = None

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._enc.close()

    def snapshot(self) -> EncoderTelemetry:
        with self._lock:
            return replace(self._telem)

    def set_roll_diameter_m(self, roll_diameter_m: float) -> None:
        with self._lock:
            self._enc.set_roll_diameter_m(roll_diameter_m)

    def set_max_speed_mpm(self, max_speed_mpm: float) -> None:
        with self._lock:
            self._enc.set_max_speed_mpm(max_speed_mpm)

    def set_invert(self, invert: bool) -> None:
        with self._lock:
            self._enc.set_invert(invert)

    def reset_unwind(self) -> None:
        with self._lock:
            self._pending_reset_unwind = True

    def reset_wound(self) -> None:
        with self._lock:
            self._pending_reset_wound = True

    def _run(self) -> None:
        last_t = monotonic()
        while not self._stop.is_set():
            now = monotonic()
            dt = now - last_t
            if dt < 1e-5:
                continue
            last_t = now
            dt = min(dt, 0.5)

            with self._lock:
                if self._pending_reset_unwind:
                    self._enc.reset_unwind()
                    self._pending_reset_unwind = False
                if self._pending_reset_wound:
                    self._enc.reset_wound()
                    self._pending_reset_wound = False
                self._telem = self._enc.poll(dt, wound_enable=True)
