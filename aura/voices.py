"""Friendly names for Kokoro voices (the model files use ids like af_sarah)."""
from __future__ import annotations

from .config import MODELS_DIR

# English voices shipped with Kokoro v1.0 (used when the voices file can't be read)
FALLBACK = [
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_alloy", "af_aoede", "af_jessica", "af_kore",
    "af_nova", "af_river",
    "am_adam", "am_michael", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_onyx", "am_puck", "am_santa",
    "bf_emma", "bf_alice", "bf_isabella", "bf_lily",
    "bm_george", "bm_daniel", "bm_fable", "bm_lewis",
]
_ACCENT = {"a": "US", "b": "UK"}
_GENDER = {"f": "female", "m": "male"}


def label(vid: str) -> str:
    """'af_sarah' -> 'Sarah · US female'"""
    if len(vid) > 3 and vid[2] == "_" and vid[0] in _ACCENT and vid[1] in _GENDER:
        return f"{vid[3:].capitalize()} · {_ACCENT[vid[0]]} {_GENDER[vid[1]]}"
    return vid


def installed_ids() -> list[str]:
    """Voice ids present in the voices file (English only), falling back to the built-in list."""
    try:
        import numpy as np
        z = np.load(MODELS_DIR / "voices-v1.0.bin", allow_pickle=True)
        names = list(z.files) if hasattr(z, "files") else []
        names = [n for n in names if n[:1] in _ACCENT and n[2:3] == "_"]
        if names:
            return names
    except Exception:
        pass
    return list(FALLBACK)


def options() -> list[dict]:
    ids = installed_ids()
    order = {v: i for i, v in enumerate(FALLBACK)}
    ids.sort(key=lambda v: (order.get(v, 999), v))
    return [{"id": v, "label": label(v)} for v in ids]
