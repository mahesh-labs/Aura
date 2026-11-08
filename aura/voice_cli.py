"""PART 2: voice conversation in the terminal (mic -> Whisper -> agent -> TTS). Run: python -m aura.voice_cli

Press Enter to start listening; it stops when you stop talking. Ctrl+C quits.
"""
from __future__ import annotations

import sys
import threading

from .agent import Agent
from .cli_chat import TermSink, confirm
from .config import DB_PATH, Config, ensure_dirs
from .db import DB
from .voice import STT, Mic, TTSPlayer, parse_yes_no


def main() -> int:
    ensure_dirs()
    cfg, db = Config(), DB(DB_PATH)
    agent = Agent(cfg, db)
    print("Loading speech recognition (first run downloads the model)…")
    stt = STT(cfg)
    stt.load()
    tts = TTSPlayer(cfg, on_level=lambda v: None, on_start=lambda: None, on_error=lambda m: print(f"[tts] {m}"))
    tts.warm()

    class VSink(TermSink):
        def sentence(self, text):
            tts.speak(text)

    sink = VSink()
    mic = Mic(cfg)
    conv = db.create_conversation()
    cancel = threading.Event()

    def voice_confirm(tool: str, desc: str) -> bool:
        tts.speak("I need your approval. " + desc.splitlines()[0][:140] + ". Say yes or no.")
        tts.wait_idle()
        print(f"\n  ❓ {desc}\n  (say yes / no)")
        for _ in range(2):
            audio = mic.utterance(lambda: False, lambda v: None, 8.0)
            ans = parse_yes_no(stt.transcribe(audio)) if audio is not None else None
            if ans is not None:
                return ans
        return False

    print("Ready. Press Enter, then speak. Ctrl+C to quit.")
    while True:
        try:
            input("\n[Enter] to talk > ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        print("🎙  listening…")
        audio = mic.utterance(lambda: False, lambda v: None, 8.0)
        if audio is None:
            print("(heard nothing)")
            continue
        text = stt.transcribe(audio)
        print(f"you> {text}")
        if not text:
            continue
        agent.run_turn(conv, text, voice=True, cancel=cancel, sink=sink, confirm=voice_confirm)
        tts.wait_idle()


if __name__ == "__main__":
    sys.exit(main())
