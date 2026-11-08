"""Agent loop: build prompt -> stream from Ollama -> run tool calls -> repeat. Qt-free."""
from __future__ import annotations

import datetime as _dt
import json
import re
import threading
import time
from pathlib import Path

from .db import DB
from .llm import LLMError, OllamaClient
from .tools import REGISTRY, Registry

# ------------------------------------------------------------------ speech helpers
_SENT_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


class SentenceSplitter:
    """Turns a token stream into whole sentences so TTS can start before the reply is finished."""

    def __init__(self, min_len: int = 14):
        self.buf = ""
        self.min_len = min_len

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while True:
            cut = None
            for m in _SENT_BREAK.finditer(self.buf):
                if m.start() >= self.min_len:
                    cut = m
                    break
            if cut is None:
                return out
            s = self.buf[: cut.start()].strip()
            self.buf = self.buf[cut.end():]
            if s:
                out.append(s)

    def flush(self) -> list[str]:
        s, self.buf = self.buf.strip(), ""
        return [s] if s else []


def speakable(text: str) -> str:
    """Strip markdown/code/URLs so the TTS doesn't read symbols aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[`*_#>~|]", "", text)
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------ sink
class Sink:
    """Receives live events from a turn. The Qt backend subclasses this."""

    def message_added(self, conv_id: int, msg: dict) -> None: ...
    def message_updated(self, conv_id: int, msg_id: int, patch: dict) -> None: ...
    def sentence(self, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def action(self, row: dict) -> None: ...
    def error(self, text: str) -> None: ...


def format_elapsed(ms: int) -> str:
    s = ms / 1000
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{round(s)} s"
    return f"{int(s // 60)} min {int(round(s % 60))} s"


def _system_prompt(cfg, voice: bool) -> str:
    now = _dt.datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M")
    who = cfg["user_name"] or "the user"
    p = (
        f"You are Aura, a helpful assistant running locally on {who}'s Linux PC "
        f"(CachyOS/Arch, KDE Plasma on Wayland). Home folder: {Path.home()}. Now: {now}.\n"
        "You can act on the computer by calling tools. Rules:\n"
        "- To do something, call the matching tool. Never claim an action succeeded unless the tool "
        "result says so; if a tool errors, say so plainly.\n"
        "- If the user's request is ambiguous or risky, ask one short clarifying question first.\n"
        "- Never invent file paths or app names; search or list first when unsure.\n"
        "- For destructive actions the system asks the user for approval itself; just call the tool.\n"
        "- Never change volume, mute or media playback unless the user explicitly asks for it.\n"
        "- If the user replies to an approval request with new instructions instead of yes/no, follow them "
        "(adjust the action and ask again if needed).\n"
        "- To see what is on the screen or to guide the user through something they have open, call "
        "look_at_screen (point=true highlights the spot). Guide one step at a time and say what to click. "
        "The user may have several monitors: when they say screens/monitors in the plural, or what they need might be "
        "on another monitor, call it with all_screens=true.\n"
        "- You can operate the mouse and keyboard: click_element (finds a thing by description, highlights it, clicks), "
        "type_text, press_keys, scroll_mouse. To type into an app: click_element on its text area, then type_text. "
        "Do one action at a time and check the result; never click something you could not find.\n"
        "- Keep answers concise."
    )
    if voice:
        p += ("\nThe user is talking to you by voice and your reply will be spoken aloud. Answer in one to "
              "three short, plain sentences. No markdown, lists, emojis, code blocks or URLs.")
    if cfg["extra_instructions"]:
        p += "\n" + cfg["extra_instructions"]
    return p


def _to_ollama(r: dict) -> dict:
    if r["role"] == "assistant":
        m = {"role": "assistant", "content": r["content"] or ""}
        if r.get("tool_calls"):
            m["tool_calls"] = r["tool_calls"]
        return m
    if r["role"] == "tool":
        return {"role": "tool", "content": r["content"] or "", "tool_name": r.get("tool_name") or ""}
    return {"role": "user", "content": r["content"] or ""}


class Agent:
    def __init__(self, cfg, db: DB, llm: OllamaClient | None = None, registry: Registry | None = None):
        self.cfg, self.db = cfg, db
        self.llm = llm or OllamaClient(cfg)
        self.tools = registry or REGISTRY

    # -------------------------------------------------------------- prompt
    def build_messages(self, conv_id: int, voice: bool) -> list[dict]:
        rows = self.db.get_messages(conv_id)
        budget = int(int(self.cfg["num_ctx"]) * 3.0 * 0.6)    # rough chars; leaves room for tools + reply
        kept, used = [], 0
        for r in reversed(rows):
            m = _to_ollama(r)
            size = len(json.dumps(m, ensure_ascii=False))
            if kept and used + size > budget:
                break
            kept.append(m)
            used += size
        kept.reverse()
        while kept and kept[0]["role"] != "user":      # never start mid tool-exchange
            kept.pop(0)
        return [{"role": "system", "content": _system_prompt(self.cfg, voice)}] + kept

    # -------------------------------------------------------------- turn
    def run_turn(self, conv_id: int, text: str, *, voice: bool, cancel: threading.Event,
                 sink: Sink, confirm) -> None:
        t_start = time.time()
        self._revisions = 0
        last_reply: int | None = None
        user = self.db.add_message(conv_id, "user", text, source="voice" if voice else "text")
        sink.message_added(conv_id, user)
        if self.db.conversation_title(conv_id) in (None, "New chat"):
            self.db.rename_conversation(conv_id, (text.strip().splitlines() or ["New chat"])[0][:48])

        tool_schemas = self.tools.schemas(self.cfg)
        splitter = SentenceSplitter()
        finished_cleanly = False

        for _ in range(int(self.cfg["max_steps"])):
            if cancel.is_set():
                break
            sink.status("Thinking")
            msgs = self.build_messages(conv_id, voice)
            asst: dict | None = None
            content, calls = "", []
            try:
                for ev in self.llm.chat_stream(msgs, tool_schemas, cancel):
                    if ev["content"]:
                        content += ev["content"]
                        if asst is None:
                            asst = self.db.add_message(conv_id, "assistant", "")
                            sink.message_added(conv_id, asst)
                        sink.message_updated(conv_id, asst["id"], {"content": content})
                        if voice:
                            for s in splitter.feed(ev["content"]):
                                s = speakable(s)
                                if s:
                                    sink.sentence(s)
                    if ev["tool_calls"]:
                        calls.extend(ev["tool_calls"])
            except LLMError as e:
                sink.error(str(e))
                err = self.db.add_message(conv_id, "assistant", f"⚠️ {e}")
                sink.message_added(conv_id, err)
                return

            if asst is None and calls:
                asst = self.db.add_message(conv_id, "assistant", "")
                sink.message_added(conv_id, asst)
            if asst is not None:
                self.db.update_message(asst["id"], content=content, tool_calls=calls or None)
            if cancel.is_set():
                break
            if not calls:
                if asst is None:
                    asst = self.db.add_message(conv_id, "assistant", "(no response)")
                    sink.message_added(conv_id, asst)
                last_reply = asst["id"]
                finished_cleanly = True
                break
            for call in calls:
                if cancel.is_set():
                    break
                self._run_tool(conv_id, call, sink, confirm, cancel)
        else:
            m = self.db.add_message(conv_id, "assistant", "I stopped because I hit the step limit for one request.")
            sink.message_added(conv_id, m)

        if last_reply is not None:                      # show how long the whole turn took
            ms = int((time.time() - t_start) * 1000)
            self.db.update_message(last_reply, elapsed_ms=ms)
            sink.message_updated(conv_id, last_reply, {"elapsed": format_elapsed(ms)})

        if voice and (finished_cleanly or not cancel.is_set()):
            for s in splitter.flush():
                s = speakable(s)
                if s:
                    sink.sentence(s)

    # -------------------------------------------------------------- tools
    def _run_tool(self, conv_id: int, call: dict, sink: Sink, confirm, cancel: threading.Event) -> None:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        tool = self.tools.get(name)
        off = name in (self.cfg["disabled_tools"] or [])
        t0 = time.time()
        status = "ok"
        if tool is None or off:
            result, status = f"Error: unknown or disabled tool '{name}'.", "error"
        else:
            sink.status(f"Running {name}")
            answer: bool | str = True
            if self.tools.needs_confirm(tool, self.cfg):
                answer = confirm(name, tool.describe_call(args))
            if isinstance(answer, str) and answer.strip():       # user replied with instructions instead of yes/no
                self._revisions += 1
                if self._revisions > 3:
                    result = ("The user keeps changing the request. Stop and ask them what exactly they want. "
                              f"Their latest reply: {answer.strip()!r}")
                else:
                    result = (f"The action was NOT run. The user replied: {answer.strip()!r}. "
                              "Follow their instruction; if you still need to run something, call the tool again "
                              "with the updated arguments (they will be asked to approve again).")
                status = "revised"
            elif not answer:
                result, status = "The user denied this action. Do not retry it; tell them it was not done.", "denied"
            else:
                try:
                    result = str(tool.fn(**args))
                    if result.startswith("Error"):
                        status = "error"
                except TypeError as e:
                    result, status = f"Error: bad arguments for {name}: {e}", "error"
                except Exception as e:  # tools must never crash the agent
                    result, status = f"Error: {type(e).__name__}: {e}", "error"
        result = result[:6000]
        row = self.db.log_action(conv_id, name, args, result, status, int((time.time() - t0) * 1000))
        sink.action(row)
        tm = self.db.add_message(conv_id, "tool", result, tool_name=name, tool_args=args)
        sink.message_added(conv_id, tm)
