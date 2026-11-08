"""Qt-free orchestration: conversations, text turns, voice sessions, approvals.

The UI layer only forwards events from `emit` and calls the public methods, which
keeps all behaviour testable without a display.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Any, Callable

from .agent import Agent, Cancelled, CancelToken
from .config import DB_PATH, Config
from .db import DB
from .llm import LLMError, OllamaClient, SentenceSplitter
from .tools import ToolContext, ToolRegistry, default_registry
from .voice import VoiceIO, VoiceUnavailable

log = logging.getLogger("aura.controller")


class Controller:
    def __init__(
        self,
        cfg: Config | None = None,
        db: DB | None = None,
        emit: Callable[[dict], None] | None = None,
        voice_factory: Callable[[Config, Callable[[float], None]], Any] | None = None,
        tools: ToolRegistry | None = None,
    ):
        self.cfg = cfg or Config()
        self.db = db or DB(DB_PATH)
        self.emit: Callable[[dict], None] = emit or (lambda e: None)
        self._voice_factory = voice_factory or VoiceIO
        self.tools = tools or default_registry(ToolContext(notify=self._notify, speak=self._speak_async))
        self.agent = Agent(self.cfg, self.db, self.tools)

        self.state = "idle"
        self.conv_id: int | None = None
        self._voice: Any = None
        self._lock = threading.RLock()
        self._cancel: CancelToken | None = None
        self._mode = "text"
        self._confirms: dict[str, tuple[threading.Event, dict]] = {}
        self._voice_session_active = False

    # ------------------------------------------------------------ plumbing
    def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.emit({"type": "state", "state": state})

    def _level(self, v: float) -> None:
        self.emit({"type": "level", "value": float(v)})

    def voice(self):
        with self._lock:
            if self._voice is None:
                self._voice = self._voice_factory(self.cfg, self._level)
            return self._voice

    def preload_voice(self) -> None:
        def work():
            try:
                self.voice().preload()
            except Exception:
                log.exception("voice preload failed")

        threading.Thread(target=work, daemon=True, name="aura-preload").start()

    def _notify(self, title: str, body: str) -> None:
        try:
            subprocess.Popen(["notify-send", "-a", "Aura", title, body])
        except OSError:
            pass

    def _speak_async(self, text: str) -> None:
        try:
            self.voice().speaker.say(text)
        except Exception:
            log.debug("speak failed", exc_info=True)

    # ------------------------------------------------------------ conversations
    def list_conversations(self) -> list[dict]:
        return self.db.list_conversations()

    def new_conversation(self) -> None:
        self.conv_id = None
        self.emit({"type": "conversation", "id": None, "items": []})

    def open_conversation(self, conv_id: int) -> None:
        if self.db.get_conversation(conv_id) is None:
            return
        self.conv_id = conv_id
        self.emit({"type": "conversation", "id": conv_id, "items": self.ui_items(conv_id)})

    def delete_conversation(self, conv_id: int) -> None:
        self.db.delete_conversation(conv_id)
        if self.conv_id == conv_id:
            self.new_conversation()
        self.emit({"type": "conversations_changed"})

    def rename_conversation(self, conv_id: int, title: str) -> None:
        if title.strip():
            self.db.rename_conversation(conv_id, title.strip()[:80])
            self.emit({"type": "conversations_changed"})

    def prepare_popup(self) -> None:
        """Quick-chat opens on the current conversation if it is recent, else a fresh one."""
        if self.state != "idle":
            return
        minutes = float(self.cfg.get("ui.chat_resume_minutes", 10))
        if self.conv_id is not None:
            conv = self.db.get_conversation(self.conv_id)
            if conv and time.time() - conv["updated"] <= minutes * 60:
                return
        self.new_conversation()

    def _ensure_conversation(self, first_text: str, mode: str) -> int:
        if self.conv_id is None or self.db.get_conversation(self.conv_id) is None:
            title = " ".join(first_text.split())[:60] or "New chat"
            self.conv_id = self.db.create_conversation(title, mode)
            self.emit({"type": "conversation_started", "id": self.conv_id})
            self.emit({"type": "conversations_changed"})
        return self.conv_id

    def ui_items(self, conv_id: int) -> list[dict]:
        items: list[dict] = []
        for r in self.db.get_messages(conv_id):
            if r["role"] == "user":
                items.append({"role": "user", "text": r["content"]})
            elif r["role"] == "assistant" and r["content"].strip():
                items.append({"role": "assistant", "text": r["content"]})
            elif r["role"] == "tool":
                meta = r.get("meta") or {}
                items.append({
                    "role": "tool", "name": r["tool_name"] or "tool",
                    "text": meta.get("summary") or r["tool_name"] or "tool",
                    "status": r["status"] or "ok", "detail": r["content"],
                })
        return items

    # ------------------------------------------------------------ turns
    def _begin(self, fn: Callable[[CancelToken], None]) -> None:
        with self._lock:
            self._cancel_locked()
            tok = CancelToken()
            self._cancel = tok
        threading.Thread(target=self._wrap, args=(fn, tok), daemon=True, name="aura-turn").start()

    def _cancel_locked(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
            self._cancel = None
        if self._voice is not None:
            try:
                self._voice.speaker.stop()
            except Exception:
                pass

    def _wrap(self, fn: Callable[[CancelToken], None], tok: CancelToken) -> None:
        try:
            fn(tok)
        except Cancelled:
            pass
        except VoiceUnavailable as e:
            self.emit({"type": "error", "text": f"Voice is not available: {e}"})
        except LLMError as e:
            self.emit({"type": "error", "text": str(e)})
        except Exception as e:
            log.exception("turn failed")
            self.emit({"type": "error", "text": f"Unexpected error: {e}"})
        finally:
            with self._lock:
                if self._cancel is tok:
                    self._cancel = None
                    self._voice_session_active = False
                    self.set_state("idle")
                    self.emit({"type": "caption", "text": ""})
                    self.emit({"type": "blob", "active": False})
                    self.emit({"type": "assistant_end"})
                    self.emit({"type": "confirm_done"})
                    self.emit({"type": "conversations_changed"})

    def cancel(self) -> None:
        with self._lock:
            self._cancel_locked()
            self._voice_session_active = False
            if self._voice is not None:
                self._voice.recorder.finish_now()
        self.set_state("idle")
        self.emit({"type": "blob", "active": False})
        self.emit({"type": "caption", "text": ""})
        self.emit({"type": "confirm_done"})

    def send_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._begin(lambda tok: self._chat_turn(text, "text", tok))

    def _chat_turn(self, text: str, mode: str, tok: CancelToken) -> None:
        self._mode = mode
        conv = self._ensure_conversation(text, mode)
        self.db.add_message(conv, "user", text)
        self.emit({"type": "message", "item": {"role": "user", "text": text}})
        self.set_state("thinking")

        speaker = self.voice().speaker if mode == "voice" else None
        splitter = SentenceSplitter()

        def speak(sentence: str) -> None:
            assert speaker is not None
            speaker.say(sentence)
            self.emit({"type": "caption", "text": sentence})
            self.set_state("speaking")

        def on_event(evt: dict) -> None:
            if speaker is not None and evt["type"] == "delta":
                for s in splitter.feed(evt["text"]):
                    speak(s)
            self.emit(evt)

        self.agent.run_turn(conv, mode, on_event, self._confirm, tok)
        if speaker is not None:
            for s in splitter.flush():
                speak(s)
            speaker.wait(tok)

    # ------------------------------------------------------------ voice
    def voice_hotkey(self) -> None:
        """One key: start -> (finish speaking) -> interrupt/cancel."""
        with self._lock:
            state = self.state
        if state == "idle":
            self._begin(self._voice_session)
        elif state == "listening":
            self.voice().recorder.finish_now()
        elif state == "speaking":
            self._begin(self._voice_session)  # barge-in: stop talking, listen
        else:  # thinking
            self.cancel()

    def _voice_session(self, tok: CancelToken) -> None:
        vio = self.voice()
        self._voice_session_active = True
        self.emit({"type": "blob", "active": True})
        first = True
        try:
            while not tok.cancelled:
                self.set_state("listening")
                self.emit({"type": "caption", "text": ""})
                timeout = float(
                    self.cfg.get("voice.no_speech_timeout", 7.0)
                    if first
                    else self.cfg.get("voice.follow_up_timeout", 6.0)
                )
                audio = vio.recorder.listen(timeout, tok)
                if audio is None or tok.cancelled:
                    break
                self.set_state("thinking")
                text = vio.stt.transcribe(audio)
                tok.raise_if_cancelled()
                if not text:
                    if first:
                        self.emit({"type": "notice", "text": "I didn't catch that."})
                    break
                first = False
                self.emit({"type": "caption", "text": f"“{text}”"})
                self._chat_turn(text, "voice", tok)
                if not self.cfg.get("voice.follow_up", True):
                    break
        finally:
            try:
                vio.speaker.stop()
            except Exception:
                pass

    # ------------------------------------------------------------ approvals
    def _confirm(self, call_id: str, name: str, args: dict, summary: str, tok: CancelToken) -> bool:
        ev = threading.Event()
        box = {"ok": False}
        self._confirms[call_id] = (ev, box)
        self.emit({
            "type": "confirm", "id": call_id, "name": name, "summary": summary,
            "detail": args.get("command") or args.get("path") or "",
        })
        if self._mode == "voice":
            self._speak_async("I need your approval for that.")
        end = time.monotonic() + 180
        while not ev.wait(0.2):
            if tok.cancelled or time.monotonic() > end:
                break
        self._confirms.pop(call_id, None)
        self.emit({"type": "confirm_done"})
        return bool(box["ok"]) and not tok.cancelled

    def answer_confirm(self, call_id: str, ok: bool) -> None:
        item = self._confirms.get(call_id)
        if item:
            item[1]["ok"] = ok
            item[0].set()

    def pending_confirm_ids(self) -> list[str]:
        return list(self._confirms)

    # ------------------------------------------------------------ misc
    def settings_changed(self) -> None:
        """Drop cached engines so new STT/TTS settings take effect on next use."""
        v = self._voice
        if v is not None:
            try:
                v.stt._model = None
                v.speaker._tts = None
            except AttributeError:
                pass
        if self.cfg.get("voice.preload", True):
            self.preload_voice()

    def list_models(self) -> list[str]:
        return OllamaClient(self.cfg.get("ollama.host")).list_models()

    def actions(self, limit: int = 200) -> list[dict]:
        return self.db.list_actions(limit)

    def shutdown(self) -> None:
        self.cancel()
