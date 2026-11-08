"""Tiny synthesised UI sounds (no audio files needed). Each returns mono float32 at 24 kHz."""
from __future__ import annotations

import numpy as np

SR = 24000


def _tone(freq: float, dur: float, vol: float = 1.0, harmonics: tuple = (1.0, 0.25)) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    y = sum(a * np.sin(2 * np.pi * freq * (i + 1) * t) for i, a in enumerate(harmonics))
    y = y / max(1e-9, sum(harmonics))
    attack = np.minimum(1.0, t / 0.008)                     # no click at the start
    decay = np.exp(-t * (4.0 / dur))                        # bell-like fade
    return (y * attack * decay * vol).astype("float32")


def _gap(dur: float) -> np.ndarray:
    return np.zeros(int(SR * dur), dtype="float32")


def _seq(*parts) -> np.ndarray:
    return np.concatenate(parts)


NAMES = ("start", "stop", "approval", "warning", "error")


def make(name: str, volume: float = 0.5) -> np.ndarray:
    """Return the named sound scaled by `volume` (0..1)."""
    if name == "start":        # voice mode on: quick rising two-note chime
        y = _seq(_tone(660, 0.11), _tone(990, 0.2))
    elif name == "stop":       # voice mode off: falling
        y = _seq(_tone(880, 0.11), _tone(587, 0.22))
    elif name == "approval":   # needs your OK: two identical soft pings
        y = _seq(_tone(784, 0.13), _gap(0.05), _tone(784, 0.2))
    elif name == "warning":    # careful: two lower, buzzier beeps
        y = _seq(_tone(330, 0.16, harmonics=(1.0, 0.6, 0.35)), _gap(0.06), _tone(330, 0.22, harmonics=(1.0, 0.6, 0.35)))
    elif name == "error":      # failed: low falling tone
        y = _seq(_tone(262, 0.14, harmonics=(1.0, 0.5, 0.3)), _tone(196, 0.3, harmonics=(1.0, 0.5, 0.3)))
    else:
        return np.zeros(0, dtype="float32")
    return np.clip(y * 0.6 * max(0.0, min(1.0, float(volume))), -1, 1).astype("float32")
