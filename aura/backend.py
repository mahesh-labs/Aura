"""QObject exposed to QML as `backend`. Owns config, DB, agent, voice controller and the models.

Threading model: the agent and voice run on worker threads. They never touch Qt objects directly; they
emit the `sig_*` signals below, which are delivered on the main thread.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
import time
import uuid

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import kwin
from .agent import Agent, Sink, format_elapsed
from .config import DEFAULTS, Config, DB_PATH
from .db import DB
from .llm import OllamaClient
from . import sounds, voices
from .models import DictModel
from .tools import REGISTRY
from .voice import VoiceController, list_devices
from .wake import WakeListener

log = logging.getLogger("aura.backend")

MSG_ROLES = ["msgId", "role", "content", "source", "toolName", "toolArgs", "ts", "elapsed"]
CONV_ROLES = ["convId", "title", "when", "pinned"]
ACT_ROLES = ["actId", "when", "tool", "args", "result", "status", "ms"]
EVENT_ROLES = ["evId", "when", "kind", "title", "detail"]
EVENT_FILTERS = {"all": None, "voice": {"voice"}, "chat": {"chat"}, "tools": {"tool"},
                 "approvals": {"approval"}, "errors": {"error"}}
CORNER_POS = {"top-right": (1.0, 0.0), "top-left": (0.0, 0.0), "bottom-right": (1.0, 1.0), "bottom-left": (0.0, 1.0)}


class Pending:
    def __init__(self, text: str):
        self.text = text
        self.event = threading.Event()
        self.result = False


def _fmt_when(ts: float) -> str:
    d = _dt.datetime.fromtimestamp(ts)
    now = _dt.datetime.now()
    if d.date() == now.date():
        return d.strftime("%H:%M")
    if (now.date() - d.date()).days == 1:
        return "Yesterday"
    return d.strftime("%d %b")


def _args_str(a) -> str:
    if not a:
        return ""
    if isinstance(a, dict):
        s = ", ".join(f"{k}={v!r}" if not isinstance(v, str) else f"{k}={v}" for k, v in a.items())
    else:
        s = str(a)
    return s if len(s) <= 140 else s[:140] + "…"


def _msg_row(m: dict) -> dict:
    return {"msgId": m["id"], "role": m["role"], "content": m["content"] or "", "source": m.get("source") or "text",
            "toolName": m.get("tool_name") or "", "toolArgs": _args_str(m.get("tool_args")), "ts": m["ts"],
            "elapsed": format_elapsed(m["elapsed_ms"]) if m.get("elapsed_ms") else ""}


class _QtSink(Sink):
    def __init__(self, b: "Backend"):
        self.b = b

    def message_added(self, conv_id, msg):
        self.b.sig_msg_added.emit(conv_id, msg)

    def message_updated(self, conv_id, msg_id, patch):
        self.b.sig_msg_updated.emit(conv_id, msg_id, patch)

    def sentence(self, text):
        if self.b.voice.active and not self.b.voice.cancel.is_set():
            self.b.voice.tts.speak(text)

    def status(self, text):
        if self.b.voice.active:
            self.b.sig_caption.emit(text + "…")

    def action(self, row):
        self.b.sig_action.emit(row)
        self.b.log_event("tool", f"{row['tool']} — {row['status']}",
                         f"{row['args']}\n→ {row['result'][:600]}")

    def error(self, text):
        self.b.sig_toast.emit(text)
        self.b.sig_sound.emit("error")
        self.b.log_event("error", "Model error", text)


class _VoiceHooks:
    def __init__(self, b: "Backend"):
        self.b = b

    def state(self, s):
        self.b.sig_state.emit(s)

    def level(self, v):
        self.b.sig_level.emit(float(v))

    def caption(self, t):
        self.b.sig_caption.emit(t)

    def toast(self, t):
        self.b.sig_toast.emit(t)

    def event(self, kind, title, detail=""):
        self.b.log_event(kind, title, detail)

    def warm(self):
        self.b.llm.warm()

    def turn(self, text, cancel):
        self.b._run_turn(text, voice=True, cancel=cancel)


class Backend(QObject):
    # --- thread-crossing signals (emit from anywhere)
    sig_msg_added = Signal(int, object)
    sig_msg_updated = Signal(int, int, object)
    sig_state = Signal(str)
    sig_level = Signal(float)
    sig_caption = Signal(str)
    sig_confirm = Signal(str, str)
    sig_busy = Signal(bool)
    sig_action = Signal(object)
    sig_toast = Signal(str)
    sig_meta = Signal()
    sig_pointer = Signal(float, float, float, float, str, float, str)
    sig_convs = Signal()
    sig_active = Signal(int)
    sig_queue = Signal()
    sig_event = Signal(object)
    sig_sound = Signal(str)

    # --- QML-facing notifications
    voiceStateChanged = Signal()
    audioLevelChanged = Signal()
    captionChanged = Signal()
    busyChanged = Signal()
    activeConvChanged = Signal()
    confirmChanged = Signal()
    wakeChanged = Signal()
    queueChanged = Signal()
    settingsChanged = Signal()
    settingsReset = Signal()               # staged values were applied/reverted: UI controls must re-read
    eventFilterChanged = Signal()
    blobPreviewChanged = Signal()
    liveChanged = Signal()
    toast = Signal(str)

    def __init__(self, cfg: Config | None = None, db: DB | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or Config()
        self.db = db or DB(DB_PATH)
        self.llm = OllamaClient(self.cfg)
        self.agent = Agent(self.cfg, self.db, self.llm)
        self.voice = VoiceController(self.cfg, _VoiceHooks(self))
        self._sink = _QtSink(self)
        self.wake = WakeListener(self.cfg, self.voice.mic, self.voice, lambda m: self.sig_toast.emit(m),
                                 lambda kind, title, detail="": self.log_event(kind, title, detail))
        from .metakey import MetaHold
        self.meta = MetaHold(lambda: self.sig_meta.emit(), float(self.cfg["meta_hold_seconds"]))
        self.sig_meta.connect(lambda: self.handle_command("voice"))
        self.sig_pointer.connect(self._show_pointer)
        from . import tools as _tools
        _tools.CONTEXT.update(cfg=self.cfg, models=self.llm.list_models,
                              pointer=lambda box, label, secs, scr="": self.sig_pointer.emit(*box, label, secs, scr),
                              screens=self.screens_info,
                              toast=lambda m: self.sig_toast.emit(m))
        from .mcp_client import MCPManager
        self.mcp = MCPManager(self.cfg)
        self.win: dict = {}                       # filled by app.py: main/chat/blob windows
        self.quit_cb = None

        self._messages = DictModel(MSG_ROLES, self)
        self._convs = DictModel(CONV_ROLES, self)
        self._actions = DictModel(ACT_ROLES, self)
        self._events = DictModel(EVENT_ROLES, self)
        self._events_all: list[dict] = []        # newest first, unfiltered
        self._event_filter = "all"
        self._staged: dict = {}                  # settings changed in the UI but not applied yet
        self._revision = 0
        self._live_user, self._live_reply, self._live_msg = "", "", 0
        self._blob_preview = False
        self._row_of: dict[int, int] = {}         # message id -> model row
        self._pending: dict[str, Pending] = {}
        self._cancel = threading.Event()
        self._busy = False
        self._busy_lock = threading.Lock()
        self._queue: list[str] = []              # messages typed while Aura was busy

        self._state, self._level, self._caption = "idle", 0.0, ""
        self._confirm_id, self._confirm_text = "", ""
        self._active_conv = self.db.latest_conversation() or 0
        self._active_prop = self._active_conv

        for sig, slot in ((self.sig_msg_added, self._on_msg_added), (self.sig_msg_updated, self._on_msg_updated),
                          (self.sig_state, self._on_state), (self.sig_level, self._on_level),
                          (self.sig_caption, self._on_caption), (self.sig_confirm, self._on_confirm),
                          (self.sig_busy, self._on_busy), (self.sig_action, self._on_action),
                          (self.sig_toast, self.toast), (self.sig_convs, self._reload_convs),
                          (self.sig_active, self._on_active), (self.sig_queue, self._on_queue),
                          (self.sig_event, self._on_event), (self.sig_sound, self._sound)):
            sig.connect(slot)

        self._reload_convs()
        self._on_active(self._active_conv)
        self._actions.set_items([self._act_row(a) for a in self.db.list_actions()])
        self._events_all = [self._ev_row(e) for e in self.db.list_events()]
        self._refilter_events()
        if "blob_fx" not in self.cfg._data and self.cfg["blob_corner"] in CORNER_POS:   # older config: keep its corner
            self.cfg.set("blob_fx", CORNER_POS[self.cfg["blob_corner"]][0], save=False)
            self.cfg.set("blob_fy", CORNER_POS[self.cfg["blob_corner"]][1], save=False)

    # ================================================================ QML properties
    messages = Property(QObject, lambda s: s._messages, constant=True)
    conversations = Property(QObject, lambda s: s._convs, constant=True)
    actions = Property(QObject, lambda s: s._actions, constant=True)
    voiceState = Property(str, lambda s: s._state, notify=voiceStateChanged)
    audioLevel = Property(float, lambda s: s._level, notify=audioLevelChanged)
    caption = Property(str, lambda s: s._caption, notify=captionChanged)
    busy = Property(bool, lambda s: s._busy, notify=busyChanged)
    activeConv = Property(int, lambda s: s._active_prop, notify=activeConvChanged)
    confirmId = Property(str, lambda s: s._confirm_id, notify=confirmChanged)
    confirmText = Property(str, lambda s: s._confirm_text, notify=confirmChanged)
    wakeOn = Property(bool, lambda s: s.wake.running, notify=wakeChanged)
    queued = Property("QVariantList", lambda s: list(s._queue), notify=queueChanged)
    events = Property(QObject, lambda s: s._events, constant=True)
    eventFilter = Property(str, lambda s: s._event_filter, notify=eventFilterChanged)
    pendingCount = Property(int, lambda s: len(s._staged), notify=settingsChanged)
    settingsRevision = Property(int, lambda s: s._revision, notify=settingsReset)
    blobPreview = Property(bool, lambda s: s._blob_preview, notify=blobPreviewChanged)
    liveUser = Property(str, lambda s: s._live_user, notify=liveChanged)       # what you said (voice mode)
    liveReply = Property(str, lambda s: s._live_reply, notify=liveChanged)     # Aura's reply, streaming in

    # ================================================================ main-thread slots for signals
    @Slot(str)
    def _on_state(self, s: str):
        if s != self._state:
            prev, self._state = self._state, s
            if prev == "idle" and s != "idle":              # a voice session just began
                self._live_user, self._live_reply, self._live_msg = "", "", 0
                self.liveChanged.emit()
                self._sound("start")
            elif s == "idle" and prev not in ("idle", "error"):
                self._sound("stop")
            elif s == "error":
                self._sound("error")
            self.voiceStateChanged.emit()

    @Slot(float)
    def _on_level(self, v: float):
        self._level = v
        self.audioLevelChanged.emit()

    @Slot(str)
    def _on_caption(self, t: str):
        self._caption = t
        self.captionChanged.emit()

    @Slot(bool)
    def _on_busy(self, b: bool):
        self._busy = b
        self.busyChanged.emit()
        if not b and self._queue and not self.voice.active:
            QTimer.singleShot(0, self._send_next)

    @Slot()
    def _on_queue(self):
        self.queueChanged.emit()

    def _send_next(self):
        if self._queue and not self._busy:
            text = self._queue.pop(0)
            self.queueChanged.emit()
            self.sendMessage(text)

    @Slot(str, str)
    def _on_confirm(self, cid: str, text: str):
        self._confirm_id, self._confirm_text = cid, text
        self.confirmChanged.emit()
        if cid:
            self._sound("approval")

    @Slot(int, object)
    def _on_msg_added(self, conv_id: int, msg: dict):
        if conv_id != self._active_conv:
            self.sig_convs.emit()
            return
        if self._state != "idle":                    # voice mode: feed the live text next to the blob
            if msg["role"] == "user" and msg.get("source") == "voice":
                self._live_user, self._live_reply, self._live_msg = msg["content"] or "", "", 0
                self.liveChanged.emit()
            elif msg["role"] == "assistant":
                self._live_msg, self._live_reply = msg["id"], msg["content"] or ""
                self.liveChanged.emit()
        if msg["id"] in self._row_of:
            return                                  # already loaded from the DB by _on_active (signal race)
        if msg["role"] == "assistant" and not (msg["content"] or ""):
            return                                  # shown once text arrives (tool-only turns stay hidden)
        self._row_of[msg["id"]] = self._messages.append(_msg_row(msg))
        if msg["role"] == "user":
            self._reload_convs()

    @Slot(int, int, object)
    def _on_msg_updated(self, conv_id: int, msg_id: int, patch: dict):
        if conv_id != self._active_conv:
            return
        if msg_id == self._live_msg and "content" in patch:
            self._live_reply = patch["content"] or ""
            self.liveChanged.emit()
        row = self._row_of.get(msg_id)
        if row is None:
            full = self.db.get_message(msg_id)
            full["content"] = patch.get("content", full["content"])
            self._row_of[msg_id] = self._messages.append(_msg_row(full))
        else:
            self._messages.update(row, patch)

    @Slot(object)
    def _on_action(self, row: dict):
        self._actions.prepend(self._act_row(row))
        if row.get("status") == "error":
            self._sound("warning")

    @Slot()
    def _reload_convs(self):
        self._convs.set_items([{"convId": c["convId"], "title": c["title"], "when": _fmt_when(c["updated"]),
                                "pinned": bool(c["pinned"])}
                               for c in self.db.list_conversations()])

    @Slot(int)
    def _on_active(self, cid: int):
        self._row_of.clear()
        rows = []
        if cid:
            for m in self.db.get_messages(cid):
                if m["role"] == "assistant" and not (m["content"] or ""):
                    continue
                rows.append(_msg_row(m))
        self._messages.set_items(rows)
        for i, r in enumerate(rows):
            self._row_of[r["msgId"]] = i
        self._active_prop = cid
        self.activeConvChanged.emit()

    @staticmethod
    def _ev_row(e: dict) -> dict:
        return {"evId": e["id"], "when": _dt.datetime.fromtimestamp(e["ts"]).strftime("%d %b %H:%M:%S"),
                "kind": e["kind"], "title": e["title"], "detail": e["detail"] or ""}

    def _refilter_events(self) -> None:
        kinds = EVENT_FILTERS.get(self._event_filter)
        self._events.set_items([e for e in self._events_all if kinds is None or e["kind"] in kinds])

    @Slot(object)
    def _on_event(self, row: dict):
        r = self._ev_row(row)
        self._events_all.insert(0, r)
        del self._events_all[1000:]
        kinds = EVENT_FILTERS.get(self._event_filter)
        if kinds is None or r["kind"] in kinds:
            self._events.prepend(r)

    @Slot(str)
    def _sound(self, name: str):
        """Play a UI sound (respects the Sounds settings). Safe to call from any thread via sig_sound."""
        try:
            if not self.cfg["sounds_enabled"]:
                return
            audio = sounds.make(name, float(self.cfg["sounds_volume"]))
            if audio.size:
                self.voice.tts.play_sound(audio, sounds.SR)
        except Exception:
            log.exception("could not play sound %s", name)

    @Slot(str)
    def playSound(self, name: str):
        """Settings page: test a sound with the currently applied volume."""
        self._sound(name)

    @Slot(str)
    def setEventFilter(self, name: str):
        if name in EVENT_FILTERS and name != self._event_filter:
            self._event_filter = name
            self._refilter_events()
            self.eventFilterChanged.emit()

    @staticmethod
    def _act_row(a: dict) -> dict:
        return {"actId": a["id"], "when": _dt.datetime.fromtimestamp(a["ts"]).strftime("%d %b %H:%M:%S"),
                "tool": a["tool"], "args": _args_str(json.loads(a["args"]) if a["args"] else {}),
                "result": a["result"] or "", "status": a["status"], "ms": a["ms"]}

    # ================================================================ conversations
    def _ensure_conv(self) -> int:
        if not self._active_conv:
            self._active_conv = self.db.create_conversation()
            self.sig_active.emit(self._active_conv)
            self.sig_convs.emit()
        return self._active_conv

    def _fresh_if_stale(self, minutes: float = 30) -> None:
        """Start a new conversation when the last one has been idle a while (hotkey use shouldn't drag old context)."""
        cid = self._active_conv
        if cid and not self._busy:
            upd = self.db.conversation_updated(cid)
            if upd and time.time() - upd > minutes * 60:
                self._active_conv = 0
                self.sig_active.emit(0)

    @Slot()
    def newConversation(self):
        if self._busy:
            self.toast.emit("Wait for the current reply or press stop first.")
            return
        self._active_conv = 0
        self._on_active(0)

    @Slot(int)
    def openConversation(self, cid: int):
        self._active_conv = cid
        self._on_active(cid)

    @Slot(int, str)
    def renameConversation(self, cid: int, title: str):
        title = " ".join((title or "").split())[:80]
        if title:
            self.db.rename_conversation(cid, title)
            self._reload_convs()

    @Slot(int, bool)
    def setPinned(self, cid: int, pinned: bool):
        self.db.set_pinned(cid, pinned)
        self._reload_convs()

    @Slot(int)
    def deleteConversation(self, cid: int):
        self.db.delete_conversation(cid)
        if cid == self._active_conv:
            self._active_conv = 0
            self._on_active(0)
        self._reload_convs()

    # ================================================================ running turns
    def log_event(self, kind: str, title: str, detail: str = "") -> None:
        """Thread-safe: writes to the activity log (shown on the Activity page)."""
        try:
            row = self.db.log_event(kind, title, detail, self._active_conv or None)
            self.sig_event.emit(row)
        except Exception:
            log.exception("could not write event")

    def _run_turn(self, text: str, *, voice: bool, cancel: threading.Event) -> None:
        """Blocking; called on a worker thread."""
        conv = self._ensure_conv()
        self.sig_busy.emit(True)
        kind = "voice" if voice else "chat"
        self.log_event(kind, "You said" if voice else "You wrote", text)
        try:
            self.agent.run_turn(conv, text, voice=voice, cancel=cancel, sink=self._sink, confirm=self._confirm)
            last = next((m for m in reversed(self.db.get_messages(conv)) if m["role"] == "assistant" and m["content"]), None)
            if last:
                took = f" ({format_elapsed(last['elapsed_ms'])})" if last.get("elapsed_ms") else ""
                self.log_event(kind, "Aura replied" + took, last["content"])
        except Exception as e:
            log.exception("turn failed")
            self.sig_toast.emit(f"Error: {e}")
            self.log_event("error", "Turn failed", str(e))
        finally:
            self.sig_busy.emit(False)

    @Slot(str)
    def sendMessage(self, text: str):
        """Send a message. If Aura is busy with a text turn the message is queued and sent afterwards."""
        text = (text or "").strip()
        if not text:
            return
        with self._busy_lock:
            if self.voice.active:
                self.toast.emit("Voice mode is active — stop it or speak instead.")
                return
            if self._busy:
                self._queue.append(text)
                self.sig_queue.emit()
                return
            self._busy = True
        self.sig_busy.emit(True)
        self._cancel = threading.Event()
        cancel = self._cancel
        threading.Thread(target=self._run_turn, args=(text,), kwargs={"voice": False, "cancel": cancel},
                         daemon=True, name="text-turn").start()

    @Slot(int)
    def removeQueued(self, index: int):
        if 0 <= index < len(self._queue):
            self._queue.pop(index)
            self.queueChanged.emit()

    @Slot()
    def stop(self):
        self._queue.clear()
        self.queueChanged.emit()
        self._cancel.set()
        self.voice.stop()

    def _close_input(self) -> None:
        from .inputctl import CONTROLLER
        CONTROLLER.close()

    def shutdown(self) -> None:
        """Stop everything that could keep the process (or the blob) alive."""
        for fn in (self._cancel.set, self.voice.stop, self.wake.stop, self.meta.stop, self.mcp.stop, self._close_input, self.voice.tts.release):
            try:
                fn()
            except Exception:
                pass

    # ---- confirmation of risky tool calls
    def _confirm(self, tool: str, description: str):
        """Returns True / False, or a string when the user answered with new instructions."""
        pend = Pending(description)
        pid = uuid.uuid4().hex[:8]
        self._pending[pid] = pend
        self.sig_confirm.emit(pid, description)
        self.log_event("approval", f"Approval requested: {tool}", description)
        in_voice = self.voice.active and threading.current_thread().name == "voice-session"
        cancel = self.voice.cancel if in_voice else self._cancel
        try:
            if in_voice:
                spoken = " ".join(description.split())
                if len(spoken) > 220:
                    spoken = spoken[:220] + " and more"
                self.voice.ask_confirm(f"I'm about to: {spoken}. Say yes, no, or tell me what to change.", pend)
            end = time.time() + (60 if in_voice else 180)
            while not pend.event.wait(0.25):
                if cancel.is_set() or time.time() > end:
                    pend.result = False
                    break
        finally:
            self._pending.pop(pid, None)
            self.sig_confirm.emit("", "")
        r = pend.result
        self.log_event("approval", "Approved" if r is True else ("Denied" if r is False else "You replied instead"),
                       r if isinstance(r, str) else description)
        return r

    @Slot(str, bool)
    def confirmResponse(self, pid: str, ok: bool):
        p = self._pending.get(pid)
        if p:
            p.result = ok
            p.event.set()

    @Slot(str, str)
    def confirmReply(self, pid: str, text: str):
        """Answer an approval request with instructions instead of yes/no."""
        p = self._pending.get(pid)
        text = (text or "").strip()
        if p and text:
            p.result = text
            p.event.set()

    # ================================================================ voice / windows / commands
    @Slot()
    def toggleVoice(self):
        if self.voice.active:
            self.voice.stop()
        else:
            self._fresh_if_stale()
            self.voice.start()

    @Slot()
    def toggleChat(self):
        w = self.win.get("chat")
        if not w:
            return
        if w.isVisible():
            w.hide()
        else:
            self._fresh_if_stale()
            w.show()
            w.raise_()
            w.requestActivate()

    @Slot()
    def hideChat(self):
        if self.win.get("chat"):
            self.win["chat"].hide()

    @Slot()
    def showMain(self):
        w = self.win.get("main")
        if w:
            w.show()
            w.raise_()
            w.requestActivate()

    @Slot()
    def quit(self):
        if self.quit_cb:
            self.quit_cb()

    def handle_command(self, cmd: str) -> str:
        cmd = cmd.strip().lower()
        if cmd == "voice":
            self.toggleVoice()
        elif cmd == "voice-start":
            if not self.voice.active:
                self.toggleVoice()
        elif cmd == "voice-stop":
            self.voice.stop()
        elif cmd == "wake":
            self.setSetting("wake_enabled", not self.wake.running)
        elif cmd == "wake-on":
            self.setSetting("wake_enabled", True)
        elif cmd == "wake-off":
            self.setSetting("wake_enabled", False)
        elif cmd == "chat":
            self.toggleChat()
        elif cmd == "chat-show":
            if self.win.get("chat") and not self.win["chat"].isVisible():
                self.toggleChat()
        elif cmd == "chat-hide":
            self.hideChat()
        elif cmd == "new-chat":
            self.newConversation()
        elif cmd == "show":
            self.showMain()
        elif cmd == "point-test":
            self.sig_pointer.emit(0.35, 0.4, 0.65, 0.55, "Pointer test", float(self.cfg["pointer_seconds"]), self.screens_info()["target"])
        elif cmd == "look-test":
            def _go():
                from .tools import look_at_screen
                r = look_at_screen("Describe what is on this screen and point at the most important thing.", True)
                log.info("look-test: %s", r)
                self.sig_toast.emit(r[:200])
            threading.Thread(target=_go, daemon=True).start()
            return "looking..."
        elif cmd == "quit":
            QTimer.singleShot(50, self.quit)
        elif cmd == "status":
            return (f"state={self._state} busy={self._busy} model={self.cfg['model']} "
                    f"wake={'on' if self.wake.running else 'off'}")
        elif cmd == "ping":
            return "pong"
        else:
            return f"unknown command: {cmd}"
        return "ok"

    # ================================================================ settings
    @Slot(str, result="QVariant")
    def getSetting(self, key: str):
        return self.cfg.get(key)

    @staticmethod
    def _coerce(key: str, value):
        """Convert a UI value to the type of the setting's default; raises ValueError/TypeError if impossible."""
        default = DEFAULTS.get(key)
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int):
            return int(float(value))
        if isinstance(default, float):
            return float(value)
        if isinstance(default, str):
            return str(value)
        return value

    def _apply_setting(self, key: str, value, rules: bool = True) -> None:
        self.cfg.set(key, value)
        if key == "tts_engine":
            self.voice.invalidate()
        if rules and key.startswith("blob_"):
            self.applyWindowRules()
        if key == "meta_hold_enabled":
            self.meta.start() if value else self.meta.stop()
        elif key == "meta_hold_seconds":
            self.meta.hold_s = float(value)
        if key == "wake_enabled":
            self.wake.start() if value else self.wake.stop()
            self.wakeChanged.emit()
        elif key.startswith("wake_"):
            self.wake.stt._model = None            # reload with the new model next time

    def screens_info(self) -> dict:
        """Monitor layout (logical pixels), the monitor under the mouse, and the monitor Aura should look at."""
        try:
            from PySide6.QtGui import QCursor, QGuiApplication
            scr = [{"name": sc.name(), "x": sc.geometry().x(), "y": sc.geometry().y(),
                    "w": sc.geometry().width(), "h": sc.geometry().height()} for sc in QGuiApplication.screens()]
            cur = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            cursor = cur.name() if cur else (scr[0]["name"] if scr else "")
        except Exception:
            return {"screens": [], "cursor": "", "target": ""}
        want = str(self.cfg["screen_target"] or "")
        target = want if any(s["name"] == want for s in scr) else cursor
        return {"screens": scr, "cursor": cursor, "target": target}

    def _show_pointer(self, x1, y1, x2, y2, label, secs, screen_name="") -> None:
        """Dim the screen under the mouse and highlight a box (runs on the Qt thread)."""
        win = self.win.get("pointer")
        if win is None:
            return
        try:
            from PySide6.QtGui import QCursor, QGuiApplication
            sc = next((x for x in QGuiApplication.screens() if x.name() == screen_name), None) \
                or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            win.setScreen(sc)
            for k, v in (("fx1", x1), ("fy1", y1), ("fx2", x2), ("fy2", y2), ("label", label), ("hold", secs)):
                win.setProperty(k, v)
            win.setProperty("request", int(win.property("request") or 0) + 1)
        except Exception:
            log.exception("pointer overlay failed")

    @Slot(result=str)
    def metaStatus(self) -> str:
        return self.meta.status

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value):
        """Change and apply a setting immediately (used by the tray and CLI)."""
        try:
            value = self._coerce(key, value)
        except (TypeError, ValueError):
            return
        self._staged.pop(key, None)
        self._apply_setting(key, value)
        self._bump()

    def _bump(self) -> None:
        self._revision += 1
        self.settingsChanged.emit()
        self.settingsReset.emit()

    # ---- staged settings: edit freely in the UI, then Apply or Revert
    @Slot(str, "QVariant")
    def stageSetting(self, key: str, value):
        try:
            value = self._coerce(key, value)
        except (TypeError, ValueError):
            return
        if value == self.cfg.get(key):
            self._staged.pop(key, None)
        else:
            self._staged[key] = value
        self.settingsChanged.emit()

    @Slot(str, result="QVariant")
    def getStaged(self, key: str):
        return self._staged[key] if key in self._staged else self.cfg.get(key)

    @Slot(str, bool)
    def stageToolEnabled(self, name: str, on: bool):
        self._stage_tool("enabled", name, on, self._tool_state(name)[0])

    @Slot(str, bool)
    def stageToolAsk(self, name: str, ask: bool):
        self._stage_tool("ask", name, ask, self._tool_state(name)[1])

    def _tool_state(self, name: str) -> tuple[bool, bool]:
        for t in REGISTRY.listing(self.cfg):
            if t["name"] == name:
                return bool(t["enabled"]), bool(t["ask"])
        return True, False

    def _stage_tool(self, what: str, name: str, value: bool, current: bool) -> None:
        key = f"tool:{what}:{name}"
        if bool(value) == bool(current):
            self._staged.pop(key, None)
        else:
            self._staged[key] = bool(value)
        self.settingsChanged.emit()

    @Slot(result=int)
    def applyStaged(self) -> int:
        n, rules = 0, False
        for key, value in list(self._staged.items()):
            if key.startswith("tool:enabled:"):
                self.setToolEnabled(key.split(":", 2)[2], value)
            elif key.startswith("tool:ask:"):
                self.setToolAsk(key.split(":", 2)[2], value)
            else:
                self._apply_setting(key, value, rules=False)
                rules = rules or key.startswith("blob_")
            n += 1
        self._staged.clear()
        if rules:
            self.applyWindowRules()
        self._bump()
        if n:
            self.log_event("system", f"Applied {n} setting{'s' if n != 1 else ''}")
        return n

    @Slot()
    def revertStaged(self):
        self._staged.clear()
        self._bump()

    # ---- blob position helpers
    @Slot(result="QVariantList")
    def monitors(self):
        try:
            from PySide6.QtGui import QGuiApplication
            return [{"name": sc.name(), "w": sc.geometry().width(), "h": sc.geometry().height()}
                    for sc in QGuiApplication.screens()]
        except Exception:
            return []

    @Slot(int, int, int, int)
    def setBlobMask(self, x: int, y: int, w: int, h: int):
        """Limit the blob window's *input* region to the pill/card so clicks elsewhere reach the apps below."""
        if not self.cfg["blob_clickable"]:
            return                                   # default: the blob window is fully click-through
        win = self.win.get("blob")
        if win is None:
            return
        try:
            from PySide6.QtGui import QRegion
            win.setMask(QRegion(x, y, max(1, w), max(1, h)))
        except Exception:
            log.exception("could not set the blob input region")

    @Slot()
    def testBlob(self):
        """Show the blob for a few seconds at the currently *applied* position."""
        self._blob_preview = True
        self.blobPreviewChanged.emit()
        QTimer.singleShot(3500, self._end_blob_preview)

    def _end_blob_preview(self):
        self._blob_preview = False
        self.blobPreviewChanged.emit()

    @Slot(result="QVariantList")
    def ttsVoices(self):
        return voices.options()

    @Slot(str)
    def previewVoice(self, voice_id: str):
        t = self.voice.tts
        t.stop()
        t.speak("Hi, I'm Aura. This is how I sound.", voice=voice_id or None)

    @Slot(result="QVariantList")
    def availableModels(self):
        return self.llm.list_models()

    @Slot(result="QVariantList")
    def visionModels(self):
        """Blank (= auto-detect), then installed models that can read images, then the rest."""
        from . import screen
        names = self.llm.list_models()
        cache = self.__dict__.setdefault("_vision_cache", {})
        for n in names:
            if n not in cache:
                cache[n] = screen.has_vision(self.cfg, n)
        seeing = [n for n in names if cache.get(n)]
        return [""] + seeing + [n for n in names if n not in seeing]

    @Slot(str, result="QVariantList")
    def audioDevices(self, kind: str):
        return [""] + list_devices(kind)

    @Slot(result="QVariantList")
    def toolList(self):
        out = []
        for t in REGISTRY.listing(self.cfg):
            t = dict(t)
            t["enabled"] = self._staged.get(f"tool:enabled:{t['name']}", t["enabled"])
            t["ask"] = self._staged.get(f"tool:ask:{t['name']}", t["ask"])
            out.append(t)
        return out

    @Slot(str, bool)
    def setToolEnabled(self, name: str, on: bool):
        off = set(self.cfg["disabled_tools"] or [])
        (off.discard if on else off.add)(name)
        self.cfg.set("disabled_tools", sorted(off))

    @Slot(str, bool)
    def setToolAsk(self, name: str, ask: bool):
        t = REGISTRY.get(name)
        ov = dict(self.cfg["ask_overrides"] or {})
        if t and ask == t.confirm:
            ov.pop(name, None)
        else:
            ov[name] = ask
        self.cfg.set("ask_overrides", ov)

    @Slot()
    def clearActions(self):
        self.db.clear_actions()
        self.db.clear_events()
        self._actions.set_items([])
        self._events_all = []
        self._events.set_items([])

    @Slot()
    def applyWindowRules(self):
        """Place the overlay windows. The blob gets a forced KWin window rule (reliable on Wayland); the KWin
        script additionally sets always-on-top / no taskbar flags and centres the quick chat."""
        try:
            x, y = self._blob_xy()
            from . import kde
            threading.Thread(target=kde.set_blob_rule, args=(x, y), daemon=True, name="kwin-rule").start()
            log.info("blob rule: position %s,%s", x, y)
        except Exception:
            log.exception("could not write the blob window rule")
        kwin.install(float(self.cfg["blob_fx"]), float(self.cfg["blob_fy"]), int(self.cfg["blob_margin"]),
                     str(self.cfg["blob_screen"]))

    def _blob_xy(self) -> tuple[int, int]:
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        name = str(self.cfg["blob_screen"])
        sc = next((s for s in screens if s.name() == name), None) or QGuiApplication.primaryScreen()
        g = sc.geometry()
        bw, bh = kwin.BLOB_W, kwin.BLOB_H
        m = int(self.cfg["blob_margin"])
        fx = min(1.0, max(0.0, float(self.cfg["blob_fx"])))
        fy = min(1.0, max(0.0, float(self.cfg["blob_fy"])))
        return (g.x() + m + round(fx * max(0, g.width() - bw - 2 * m)),
                g.y() + m + round(fy * max(0, g.height() - bh - 2 * m)))

    @Slot()
    def openShortcutSettings(self):
        import subprocess
        for cmd in (["systemsettings", "kcm_keys"], ["systemsettings6", "kcm_keys"]):
            try:
                subprocess.Popen(cmd, start_new_session=True)
                return
            except FileNotFoundError:
                continue
