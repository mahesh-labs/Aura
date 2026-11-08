"""Wake word ("hey aura"): keeps the mic open while idle and listens for the phrase.

Uses a small Whisper model on CPU for each burst of speech (no extra dependencies), with the wake phrase as
a prompt so Whisper is biased towards it. Local only; turn it off in Settings if you don't want an
always-open mic. "hey aura open firefox" works in one go.
"""
from __future__ import annotations

import difflib
import logging
import re
import threading
import time

from .voice import SR_IN, STT, Mic, collect_utterance

log = logging.getLogger("aura.wake")


def _norm(t: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", t.lower()).split()


def match_wake(text: str, phrases: list[str], threshold: float = 0.84) -> tuple[bool, str]:
    """True if `text` starts with one of the phrases (fuzzy). Returns (matched, remaining command text)."""
    words = _norm(text)
    if not words:
        return False, ""
    best = (0.0, 0)
    for ph in phrases:
        pw = _norm(ph)
        if not pw:
            continue
        n = len(pw)
        for take in {n, n + 1}:                         # "hey aura" may be heard as "hey a aura"
            if take > len(words):
                continue
            r = difflib.SequenceMatcher(None, " ".join(words[:take]), " ".join(pw)).ratio()
            if r > best[0]:
                best = (r, take)
    if best[0] >= threshold:
        return True, " ".join(words[best[1]:]).strip()
    return False, ""


class WakeListener:
    def __init__(self, cfg, mic: Mic, voice, toast, event=None):
        self.cfg, self.mic, self.voice, self.toast = cfg, mic, voice, toast
        self.event = event or (lambda kind, title, detail="": None)
        self.stt = STT(cfg, "wake_stt_model")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="wake-listener")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _phrases(self) -> list[str]:
        return [p.strip() for p in str(self.cfg["wake_phrases"]).split(",") if p.strip()]

    def _run(self) -> None:
        log.info("wake word listening: %s", self._phrases())
        try:
            self.stt.load()
            while not self._stop.is_set():
                if self.voice.active:
                    time.sleep(0.3)
                    continue
                rest = self._listen_until_wake()
                if rest is None:
                    continue
                log.info("wake word heard; command=%r", rest)
                self.event("voice", "Wake word heard", rest or "")
                self.voice.start(initial_text=rest or None)
                time.sleep(0.6)
        except Exception as e:
            log.exception("wake listener stopped")
            self.toast(f"Wake word stopped: {e}")
        finally:
            self._thread = None

    def _listen_until_wake(self) -> str | None:
        stop = lambda: self._stop.is_set() or self.voice.active      # noqa: E731
        with self.mic.blocks(stop) as blocks:
            while not stop():
                audio = collect_utterance(blocks, stop=stop, wait_s=3600, max_s=7, silence_ms=600,
                                          min_level=float(self.cfg["vad_min_level"]))
                if audio is None:
                    return None
                if len(audio) / SR_IN < 0.4:
                    continue
                text = self.stt.transcribe(audio, prompt="Hey Aura. Hey Aura, open Firefox.")
                ok, rest = match_wake(text, self._phrases())
                log.debug("heard %r -> %s", text, ok)
                if ok:
                    return rest
        return None
