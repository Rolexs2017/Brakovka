"""HMI sound effects (key click, save OK, error, alarm).

WAV files are generated once under ``assets/sounds/``. Playback prefers
``QSoundEffect`` (Qt Multimedia); falls back to ``aplay`` / ``winsound``.
"""

from __future__ import annotations

import logging
import math
import struct
import subprocess
import sys
import wave
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

_SOUNDS_DIR = Path(__file__).resolve().parent / "assets" / "sounds"
_RATE = 22050
# Bump to force regenerate louder WAVs on disk.
_SOUND_VERSION = 2

_enabled = True
_effects: dict[str, object] = {}
_ready = False


class Sound(str, Enum):
    KEY = "key"
    OK = "ok"
    ERROR = "error"
    ALARM = "alarm"


def _write_tone(
    path: Path,
    *,
    freqs: list[tuple[float, float]],
    volume: float = 0.92,
) -> None:
    """Write mono 16-bit WAV. ``freqs`` is list of (hz, duration_s)."""
    frames: list[int] = []
    for hz, dur in freqs:
        n = max(1, int(_RATE * dur))
        attack = max(1, int(0.004 * _RATE))
        release = max(1, int(0.010 * _RATE))
        for i in range(n):
            env = 1.0
            if i < attack:
                env = i / attack
            elif i > n - release:
                env = max(0.0, (n - i) / release)
            # Soft square-ish mix for more perceived loudness on small speakers.
            t = i / _RATE
            sine = math.sin(2.0 * math.pi * hz * t)
            odd = 0.25 * math.sin(2.0 * math.pi * (3.0 * hz) * t)
            sample = volume * env * (sine + odd)
            frames.append(int(max(-1.0, min(1.0, sample)) * 32767))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_RATE)
        wf.writeframes(b"".join(struct.pack("<h", s) for s in frames))


def _ensure_wav_files() -> dict[Sound, Path]:
    specs: dict[Sound, tuple[float, list[tuple[float, float]]]] = {
        # (wav amplitude, tones)
        Sound.KEY: (0.95, [(1100.0, 0.045)]),
        Sound.OK: (0.90, [(700.0, 0.08), (1050.0, 0.12)]),
        Sound.ERROR: (0.95, [(240.0, 0.14), (190.0, 0.16)]),
        Sound.ALARM: (1.0, [(900.0, 0.14), (450.0, 0.14), (900.0, 0.14), (450.0, 0.20)]),
    }
    ver_path = _SOUNDS_DIR / f".version-{_SOUND_VERSION}"
    regenerate = not ver_path.exists()
    if regenerate:
        _SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        for old in _SOUNDS_DIR.glob(".version-*"):
            try:
                old.unlink()
            except OSError:
                pass

    paths: dict[Sound, Path] = {}
    for sound, (amp, freqs) in specs.items():
        path = _SOUNDS_DIR / f"{sound.value}.wav"
        if regenerate or not path.exists() or path.stat().st_size < 44:
            _write_tone(path, freqs=freqs, volume=amp)
        paths[sound] = path

    if regenerate:
        ver_path.write_text(str(_SOUND_VERSION), encoding="utf-8")
    return paths


def init_sounds(*, enabled: bool = True) -> None:
    """Call once after QApplication is created."""
    global _ready, _enabled, _effects
    _enabled = bool(enabled)
    paths = _ensure_wav_files()
    _effects = {}

    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QSoundEffect

        for sound, path in paths.items():
            fx = QSoundEffect()
            fx.setSource(QUrl.fromLocalFile(str(path.resolve())))
            # Max Qt gain; loudness mainly comes from louder WAV samples.
            fx.setVolume(1.0)
            _effects[sound.value] = fx
        _ready = True
        log.info("HMI sounds: QSoundEffect (%s)", _SOUNDS_DIR)
        return
    except Exception:
        log.info("HMI sounds: QSoundEffect unavailable, using OS fallback")

    _effects = {s.value: p for s, p in paths.items()}
    _ready = True


def play(sound: Sound | str) -> None:
    if not _enabled or not _ready:
        return
    name = sound.value if isinstance(sound, Sound) else str(sound)
    target = _effects.get(name)
    if target is None:
        return

    # QSoundEffect path
    if hasattr(target, "play"):
        try:
            target.play()
            return
        except Exception:
            log.debug("QSoundEffect play failed for %s", name, exc_info=True)

    path = Path(str(target))
    if not path.exists():
        return
    try:
        if sys.platform.startswith("win"):
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            # Raspberry Pi / Linux — prefer aplay (alsa), then paplay.
            for cmd in (("aplay", "-q"), ("paplay",)):
                try:
                    subprocess.Popen(  # noqa: S603
                        [*cmd, str(path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except FileNotFoundError:
                    continue
    except Exception:
        log.debug("OS sound fallback failed for %s", name, exc_info=True)


def play_key() -> None:
    play(Sound.KEY)


def play_ok() -> None:
    play(Sound.OK)


def play_error() -> None:
    play(Sound.ERROR)


def play_alarm() -> None:
    play(Sound.ALARM)
