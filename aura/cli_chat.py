"""PART 1: terminal chat with the agent (no Qt, no audio). Run: python -m aura.cli_chat"""
from __future__ import annotations

import sys
import threading

from .agent import Agent, Sink
from .config import DB_PATH, Config, ensure_dirs
from .db import DB


class TermSink(Sink):
    def __init__(self):
        self.shown: dict[int, int] = {}

    def message_added(self, conv_id, msg):
        if msg["role"] == "tool":
            args = ", ".join(f"{k}={v}" for k, v in (msg["tool_args"] or {}).items())
            print(f"\n  ⚙ {msg['tool_name']}({args})\n    → {msg['content'][:200]}")
        elif msg["role"] == "assistant" and msg["content"]:
            print(f"\naura> {msg['content']}", end="", flush=True)
            self.shown[msg["id"]] = len(msg["content"])
        elif msg["role"] == "assistant":
            self.shown[msg["id"]] = 0

    def message_updated(self, conv_id, msg_id, patch):
        text = patch.get("content", "")
        n = self.shown.get(msg_id, 0)
        if n == 0 and text:
            print("\naura> ", end="")
        print(text[n:], end="", flush=True)
        self.shown[msg_id] = len(text)

    def error(self, text):
        print(f"\n[error] {text}")


def confirm(tool: str, description: str) -> bool:
    print(f"\n  ❓ Aura wants to: {description}")
    return input("     allow? [y/N] ").strip().lower() in ("y", "yes")


def main() -> int:
    ensure_dirs()
    cfg, db = Config(), DB(DB_PATH)
    agent = Agent(cfg, db)
    models = agent.llm.list_models()
    print(f"Aura terminal chat — model: {cfg['model']}  (installed: {', '.join(models) or 'cannot reach Ollama'})")
    print("Type a request. /new = new chat, /quit = exit. Change settings in ~/.config/aura/config.json\n")
    conv = db.create_conversation()
    sink = TermSink()
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text == "/quit":
            return 0
        if text == "/new":
            conv = db.create_conversation()
            print("(new conversation)")
            continue
        try:
            agent.run_turn(conv, text, voice=False, cancel=threading.Event(), sink=sink, confirm=confirm)
        except KeyboardInterrupt:
            print("\n(interrupted)")
        print()


if __name__ == "__main__":
    sys.exit(main())
