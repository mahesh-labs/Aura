"""Tools the agent can call. Anything that changes the system asks for confirmation by default.

Add your own: decorate a function with @tool(...). The JSON schema sent to the model is built from
`params`. Tools return a short string that is fed back to the model.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HOME = Path.home()


@dataclass
class Tool:
    name: str
    description: str
    params: dict                     # {"arg": {"type": "string", "description": "..."}}
    required: tuple
    fn: Callable
    confirm: bool = False            # ask the user before running (default)
    describe: Callable | None = None  # args -> human readable "what will happen"

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": self.params, "required": list(self.required)}}}

    def describe_call(self, args: dict) -> str:
        if self.describe:
            try:
                return self.describe(args)
            except Exception:
                pass
        return f"{self.name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"


class Registry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def add(self, t: Tool) -> None:
        self.tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def enabled(self, cfg) -> list[Tool]:
        off = set(cfg["disabled_tools"] or [])
        return [t for t in self.tools.values() if t.name not in off]

    def schemas(self, cfg) -> list[dict]:
        return [t.schema() for t in self.enabled(cfg)]

    def needs_confirm(self, t: Tool, cfg) -> bool:
        return bool((cfg["ask_overrides"] or {}).get(t.name, t.confirm))

    def listing(self, cfg) -> list[dict]:
        off = set(cfg["disabled_tools"] or [])
        return [{"name": t.name, "description": t.description, "enabled": t.name not in off,
                 "ask": self.needs_confirm(t, cfg)} for t in self.tools.values()]


REGISTRY = Registry()

# Filled in by the app: "cfg" (Config), "models" (callable -> installed Ollama models), "pointer" (callable(box, label, hold)).
CONTEXT: dict = {"cfg": None, "models": lambda: [], "pointer": None, "toast": None, "screens": None}


def tool(name: str, description: str, params: dict | None = None, required: tuple = (),
         confirm: bool = False, describe: Callable | None = None):
    def deco(fn):
        REGISTRY.add(Tool(name, description, params or {}, tuple(required), fn, confirm, describe))
        return fn
    return deco


# ---------------------------------------------------------------- helpers
def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return f"Error: `{cmd[0]}` is not installed."
    except subprocess.TimeoutExpired:
        return f"Error: `{cmd[0]}` timed out after {timeout}s."
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode != 0:
        return f"Error (exit {p.returncode}): {err or out}"
    return out or "OK"


def _spawn(cmd: list[str]) -> None:
    subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _path(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p))).resolve()


def _clip(s: str, n: int = 4000) -> str:
    return s if len(s) <= n else s[:n] + f"\n... [truncated {len(s) - n} chars]"


# ---------------------------------------------------------------- apps
_APP_DIRS = [HOME / ".local/share/applications", Path("/usr/share/applications"),
             Path("/var/lib/flatpak/exports/share/applications"),
             HOME / ".local/share/flatpak/exports/share/applications"]


def _desktop_entries() -> list[dict]:
    out, seen = [], set()
    for d in _APP_DIRS:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            if f.name in seen:
                continue
            seen.add(f.name)
            fields: dict = {}
            in_entry = False
            try:
                for line in f.read_text(errors="ignore").splitlines():
                    line = line.strip()
                    if line.startswith("["):
                        in_entry = line == "[Desktop Entry]"
                        continue
                    if in_entry and "=" in line:
                        k, v = line.split("=", 1)
                        fields.setdefault(k, v)  # first (unlocalised) value wins
            except OSError:
                continue
            if fields.get("NoDisplay") == "true" or fields.get("Hidden") == "true":
                continue
            if fields.get("Type", "Application") != "Application" or "Name" not in fields:
                continue
            out.append({"id": f.name, "path": str(f), "name": fields["Name"],
                        "generic": fields.get("GenericName", ""), "keywords": fields.get("Keywords", ""),
                        "exec": fields.get("Exec", "")})
    return out


def _find_app(query: str) -> dict | None:
    q = query.strip().lower()
    entries = _desktop_entries()
    best, best_score = None, 0
    for e in entries:
        name, gen, kw = e["name"].lower(), e["generic"].lower(), e["keywords"].lower()
        eid = e["id"].lower().removesuffix(".desktop")
        score = 0
        if q == name or q == eid:
            score = 100
        elif name.startswith(q) or eid.endswith(q):
            score = 80
        elif q in name:
            score = 60
        elif q in gen or q in kw.split(";"):
            score = 40
        elif q in e["exec"].lower():
            score = 30
        if score > best_score:
            best, best_score = e, score
    return best


@tool("open_app", "Launch an installed desktop application by name (e.g. 'firefox', 'dolphin', 'steam').",
      {"name": {"type": "string", "description": "Application name"}}, ("name",),
      describe=lambda a: f"Open application: {a.get('name')}")
def open_app(name: str) -> str:
    app = _find_app(name)
    if not app:
        names = ", ".join(sorted({e["name"] for e in _desktop_entries()})[:40])
        return f"No installed application matches '{name}'. Some installed apps: {names}"
    if shutil.which("gio"):
        _spawn(["gio", "launch", app["path"]])
    elif shutil.which("gtk-launch"):
        _spawn(["gtk-launch", app["id"]])
    else:
        return "Error: neither gio nor gtk-launch is available."
    return f"Launched {app['name']}."


@tool("list_apps", "List installed desktop applications.", {}, ())
def list_apps() -> str:
    return ", ".join(sorted({e["name"] for e in _desktop_entries()}))


@tool("open_url", "Open a URL (or a file/folder path) with the default application.",
      {"target": {"type": "string", "description": "URL or path"}}, ("target",),
      describe=lambda a: f"Open: {a.get('target')}")
def open_url(target: str) -> str:
    if not re.match(r"^[a-z][a-z0-9+.-]*://", target):
        target = str(_path(target)) if (target.startswith(("/", "~", ".")) or Path(target).exists()) \
            else "https://" + target
    _spawn(["xdg-open", target])
    return f"Opened {target}."


# ---------------------------------------------------------------- audio / media
_SINK = "@DEFAULT_AUDIO_SINK@"


@tool("get_volume", "Get the current speaker volume (percent) and mute state.", {}, ())
def get_volume() -> str:
    out = _run(["wpctl", "get-volume", _SINK])
    m = re.search(r"([\d.]+)", out)
    if not m:
        return out
    return f"Volume {round(float(m.group(1)) * 100)}%" + (" (muted)" if "MUTED" in out else "")


@tool("set_volume", "Set speaker volume to an absolute percentage (0-100).",
      {"percent": {"type": "integer", "description": "0-100"}}, ("percent",))
def set_volume(percent: int) -> str:
    p = max(0, min(100, int(percent)))
    r = _run(["wpctl", "set-volume", _SINK, f"{p}%"])
    return f"Volume set to {p}%." if not r.startswith("Error") else r


@tool("change_volume", "Raise or lower speaker volume by a relative amount (negative lowers).",
      {"delta": {"type": "integer", "description": "Percent change, e.g. 10 or -10"}}, ("delta",))
def change_volume(delta: int) -> str:
    d = int(delta)
    r = _run(["wpctl", "set-volume", "-l", "1.0", _SINK, f"{abs(d)}%{'+' if d >= 0 else '-'}"])
    return r if r.startswith("Error") else get_volume()


@tool("set_mute", "Mute, unmute or toggle the speakers.",
      {"state": {"type": "string", "enum": ["mute", "unmute", "toggle"]}}, ("state",))
def set_mute(state: str) -> str:
    v = {"mute": "1", "unmute": "0", "toggle": "toggle"}.get(state)
    if v is None:
        return "Error: state must be mute, unmute or toggle."
    r = _run(["wpctl", "set-mute", _SINK, v])
    return r if r.startswith("Error") else get_volume()


@tool("media_control", "Control the active media player (Spotify, browser, VLC, ...).",
      {"action": {"type": "string", "enum": ["play", "pause", "play_pause", "next", "previous", "stop", "status"]}},
      ("action",))
def media_control(action: str) -> str:
    cmd = {"play": "play", "pause": "pause", "play_pause": "play-pause", "next": "next",
           "previous": "previous", "stop": "stop", "status": "metadata"}.get(action)
    if not cmd:
        return "Error: unknown action."
    if action == "status":
        return _run(["playerctl", "metadata", "--format", "{{status}}: {{artist}} - {{title}}"])
    return _run(["playerctl", cmd])


# ---------------------------------------------------------------- system info
@tool("system_info", "Report CPU, memory, disk, GPU usage and uptime of this computer.", {}, ())
def system_info() -> str:
    import psutil
    lines = [f"CPU: {psutil.cpu_percent(interval=0.4)}% over {psutil.cpu_count()} threads",
             "Memory: {:.1f} / {:.1f} GiB".format(psutil.virtual_memory().used / 2**30,
                                                  psutil.virtual_memory().total / 2**30)]
    for mp in ("/", str(HOME)):
        try:
            du = psutil.disk_usage(mp)
            lines.append("Disk {}: {:.0f} / {:.0f} GiB used".format(mp, du.used / 2**30, du.total / 2**30))
            break
        except OSError:
            pass
    up = time.time() - psutil.boot_time()
    lines.append(f"Uptime: {int(up // 3600)}h {int(up % 3600 // 60)}m")
    if shutil.which("nvidia-smi"):
        g = _run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                  "--format=csv,noheader"])
        lines.append("GPU: " + g)
    return "\n".join(lines)


@tool("top_processes", "List the processes using the most CPU or memory.",
      {"sort_by": {"type": "string", "enum": ["cpu", "memory"]}, "count": {"type": "integer"}}, ())
def top_processes(sort_by: str = "cpu", count: int = 8) -> str:
    import psutil
    procs = list(psutil.process_iter(["name", "cpu_percent", "memory_percent"]))
    time.sleep(0.3)
    rows = []
    for p in procs:
        try:
            rows.append((p.info["name"], p.cpu_percent(None), p.info["memory_percent"] or 0))
        except psutil.Error:
            pass
    key = 1 if sort_by == "cpu" else 2
    rows.sort(key=lambda r: r[key], reverse=True)
    return "\n".join(f"{n}: cpu {c:.0f}%, mem {m:.1f}%" for n, c, m in rows[: max(1, min(int(count), 20))])


@tool("get_datetime", "Get the current local date and time.", {}, ())
def get_datetime() -> str:
    return _dt.datetime.now().astimezone().strftime("%A, %d %B %Y, %H:%M:%S %Z")


# ---------------------------------------------------------------- files
@tool("list_directory", "List files and folders in a directory.",
      {"path": {"type": "string", "description": "Directory, e.g. ~/Downloads"}}, ("path",))
def list_directory(path: str) -> str:
    p = _path(path)
    if not p.is_dir():
        return f"Error: {p} is not a directory."
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    lines = [("[dir]  " if i.is_dir() else "       ") + i.name for i in items[:200]]
    return f"{p} ({len(items)} items)\n" + "\n".join(lines)


@tool("search_files", "Find files by (part of) a name under a folder. Skips hidden and build folders.",
      {"query": {"type": "string"}, "root": {"type": "string", "description": "Folder to search, default home"}},
      ("query",))
def search_files(query: str, root: str = "~") -> str:
    base, q, hits = _path(root), query.lower(), []
    skip = {"node_modules", "__pycache__", "venv", ".venv", "target", "build", "dist"}
    t0 = time.time()
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in skip]
        for n in dns + fns:
            if q in n.lower():
                hits.append(os.path.join(dp, n))
        if len(hits) >= 40 or time.time() - t0 > 6:
            break
    return "\n".join(hits) if hits else f"No files matching '{query}' under {base}."


@tool("read_text_file", "Read a text file (first part only).",
      {"path": {"type": "string"}, "max_chars": {"type": "integer"}}, ("path",))
def read_text_file(path: str, max_chars: int = 4000) -> str:
    p = _path(path)
    if not p.is_file():
        return f"Error: {p} is not a file."
    try:
        return _clip(p.read_text(errors="replace"), max(200, min(int(max_chars), 12000)))
    except OSError as e:
        return f"Error: {e}"


@tool("write_text_file", "Create or overwrite (or append to) a text file.",
      {"path": {"type": "string"}, "content": {"type": "string"},
       "append": {"type": "boolean", "description": "Append instead of overwrite"}}, ("path", "content"),
      confirm=True,
      describe=lambda a: f"{'Append to' if a.get('append') else 'Write'} file {a.get('path')} "
                         f"({len(a.get('content', ''))} chars)")
def write_text_file(path: str, content: str, append: bool = False) -> str:
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a" if append else "w") as f:
        f.write(content)
    return f"{'Appended to' if append else 'Wrote'} {p}."


@tool("move_to_trash", "Move a file or folder to the trash (recoverable).",
      {"path": {"type": "string"}}, ("path",), confirm=True,
      describe=lambda a: f"Move to trash: {a.get('path')}")
def move_to_trash(path: str) -> str:
    p = _path(path)
    if not p.exists():
        return f"Error: {p} does not exist."
    return _run(["gio", "trash", str(p)])


# ---------------------------------------------------------------- shell & system actions
@tool("run_shell", "Run a shell command and return its output. Use for anything the other tools can't do.",
      {"command": {"type": "string", "description": "bash command"},
       "cwd": {"type": "string", "description": "Working directory (optional)"}}, ("command",), confirm=True,
      describe=lambda a: f"Run shell command:\n{a.get('command')}")
def run_shell(command: str, cwd: str = "~") -> str:
    try:
        p = subprocess.run(["bash", "-lc", command], cwd=str(_path(cwd)), capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 60s."
    out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")
    return _clip(f"exit {p.returncode}\n{out}".strip())


@tool("notify", "Show a desktop notification.",
      {"title": {"type": "string"}, "message": {"type": "string"}}, ("title",))
def notify(title: str, message: str = "") -> str:
    return _run(["notify-send", "-a", "Aura", title, message])


@tool("get_clipboard", "Read the text currently on the clipboard.", {}, ())
def get_clipboard() -> str:
    return _clip(_run(["wl-paste", "--no-newline"]))


@tool("set_clipboard", "Put text on the clipboard.", {"text": {"type": "string"}}, ("text",))
def set_clipboard(text: str) -> str:
    try:
        p = subprocess.run(["wl-copy"], input=text, text=True, timeout=5)
    except FileNotFoundError:
        return "Error: wl-copy (wl-clipboard) is not installed."
    return "Copied to clipboard." if p.returncode == 0 else "Error: wl-copy failed."


@tool("lock_screen", "Lock the screen.", {}, ())
def lock_screen() -> str:
    return _run(["loginctl", "lock-session"])


@tool("power_action", "Suspend, reboot or shut down the computer.",
      {"action": {"type": "string", "enum": ["suspend", "reboot", "poweroff"]}}, ("action",), confirm=True,
      describe=lambda a: f"{str(a.get('action')).upper()} the computer")
def power_action(action: str) -> str:
    if action not in ("suspend", "reboot", "poweroff"):
        return "Error: action must be suspend, reboot or poweroff."
    _spawn(["systemctl", action])
    return f"Requested {action}."


@tool("web_fetch", "Download a web page and return its readable text (needs internet).",
      {"url": {"type": "string"}}, ("url",))
def web_fetch(url: str) -> str:
    import requests
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Aura/0.1"})
        r.raise_for_status()
    except Exception as e:
        return f"Error: {e}"
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _clip(re.sub(r"\s+", " ", text).strip(), 5000)


# ---------------------------------------------------------------- screen
@tool("look_at_screen",
      "Take a screenshot of the user's current screen and look at it with a vision model. Use it when the user asks "
      "what is on the screen, asks for help with something they are looking at, or asks how to do something in an "
      "app they have open. Set point=true to also highlight the place on the screen that the user should look at "
      "or click. Give guidance one step at a time.",
      {"question": {"type": "string", "description": "What to find out, e.g. 'where is the Save button?' or 'what error is shown?'"},
       "point": {"type": "boolean", "description": "Highlight the relevant spot on the screen for the user."},
       "all_screens": {"type": "boolean", "description": "Look at EVERY monitor, not just the one under the mouse. Use it when the user says screens/monitors/displays (plural), asks about 'everything', or what they want may be on another monitor."}},
      ("question",))
def look_at_screen(question: str, point: bool = False, all_screens: bool = False) -> str:
    from . import screen
    cfg = CONTEXT["cfg"]
    if cfg is None:
        return "Error: screen reading is not set up."
    toast = CONTEXT.get("toast")
    if toast:
        toast("Looking at your screen…")
    info = {}
    try:
        info = CONTEXT["screens"]() if CONTEXT.get("screens") else {}
    except Exception:
        info = {}
    res = screen.look(cfg, question, CONTEXT["models"](), info.get("screens"), info.get("target", ""), bool(all_screens))
    if res.get("error"):
        if toast:
            toast(res["error"][:160])
        return "Error: " + res["error"]
    import logging
    logging.getLogger("aura.screen").info("look (%s): %s | target=%s", res.get("model"), res["answer"][:120], res.get("target"))
    msg = res["answer"]
    tgt = res.get("target")
    if point and tgt and CONTEXT.get("pointer"):
        try:
            CONTEXT["pointer"](tgt["box"], tgt["label"], float(cfg["pointer_seconds"]), res.get("screen") or info.get("target", ""))
            msg += f' (I highlighted "{tgt["label"]}" on the screen.)'
        except Exception as e:
            msg += f" (couldn't draw the highlight: {e})"
    elif point and not tgt:
        msg += " (I couldn't find a specific spot to highlight.)"
    return msg


@tool("point_at_screen_region",
      "Highlight a rectangle on the screen for a moment (the rest of the screen dims). Coordinates are fractions "
      "of the screen from 0 to 1. Prefer look_at_screen with point=true; use this only if you already know the place.",
      {"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"},
       "label": {"type": "string"}}, ("x1", "y1", "x2", "y2"))
def point_at_screen_region(x1: float, y1: float, x2: float, y2: float, label: str = "") -> str:
    cfg, fn = CONTEXT["cfg"], CONTEXT.get("pointer")
    if fn is None:
        return "Error: the pointer overlay is not available."
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        return "Error: coordinates must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1."
    fn([x1, y1, x2, y2], label, float(cfg["pointer_seconds"]))
    return "Highlighted."


# ---------------------------------------------------------------- mouse and keyboard
def _desktop_fraction(info: dict, screen_name: str, fx: float, fy: float) -> tuple[float, float]:
    """A point given as fractions of one monitor -> fractions of the whole desktop (what the virtual mouse uses)."""
    scr = info.get("screens") or []
    if not scr:
        return fx, fy
    s = next((x for x in scr if x["name"] == screen_name), None) or scr[0]
    ux, uy = min(x["x"] for x in scr), min(x["y"] for x in scr)
    uw = max(x["x"] + x["w"] for x in scr) - ux
    uh = max(x["y"] + x["h"] for x in scr) - uy
    return (s["x"] - ux + fx * s["w"]) / uw, (s["y"] - uy + fy * s["h"]) / uh


def _logical_point(info: dict, screen_name: str, fx: float, fy: float) -> tuple[float, float, tuple]:
    """A point given as fractions of one monitor -> logical desktop pixels, plus the desktop bounds (x, y, w, h)."""
    scr = info.get("screens") or [{"name": "", "x": 0, "y": 0, "w": 1920, "h": 1080}]
    s = next((x for x in scr if x["name"] == screen_name), None) or scr[0]
    ux, uy = min(x["x"] for x in scr), min(x["y"] for x in scr)
    uw = max(x["x"] + x["w"] for x in scr) - ux
    uh = max(x["y"] + x["h"] for x in scr) - uy
    return s["x"] + fx * s["w"], s["y"] + fy * s["h"], (ux, uy, uw, uh)


def _move_pointer(info: dict, screen_name: str, fx: float, fy: float) -> str | None:
    """Put the mouse on a point of a monitor and verify. Returns an error text, or None when it is in place."""
    from .inputctl import CONTROLLER
    kw = None
    try:
        from . import cursor
        kw = cursor.query() if cursor.available() else None
    except Exception:
        kw = None
    if kw and kw.get("screens"):                          # KWin's own monitor layout beats Qt's
        info = dict(info, screens=kw["screens"])
    x, y, bounds = _logical_point(info, screen_name, fx, fy)
    r = CONTROLLER.goto(x, y, bounds)
    if r["measured"] is not None and not r["ok"]:
        return (f"the mouse pointer would not go to the right place (wanted {round(x)},{round(y)}, got "
                f"{r['measured'][0]},{r['measured'][1]}). Run ./run.sh input and send me its output.")
    return None


def _screens_info() -> dict:
    try:
        return CONTEXT["screens"]() if CONTEXT.get("screens") else {}
    except Exception:
        return {}


@tool("click_element",
      "Find something on the screen by describing it, highlight it, and click it with the mouse. Use for 'click the close "
      "button', 'press Play', 'click the text box in Notepad', 'open the settings icon'. Describe it the way a person "
      "would: what it says or looks like and which window it is in.",
      {"description": {"type": "string", "description": "What to click, e.g. 'the red close button of the Notepad window' or 'the text area in Notepad'"},
       "action": {"type": "string", "enum": ["click", "double_click", "right_click", "highlight_only"],
                  "description": "Default click. highlight_only just points at it without clicking."},
       "all_screens": {"type": "boolean", "description": "Search every monitor (use when it may be on another monitor)."}},
      ("description",), confirm=True,
      describe=lambda a: f"{str(a.get('action') or 'click').replace('_', ' ')}: {a.get('description')}")
def click_element(description: str, action: str = "click", all_screens: bool = False) -> str:
    from . import screen
    from .inputctl import CONTROLLER, InputError
    cfg = CONTEXT["cfg"]
    if cfg is None:
        return "Error: screen control is not set up."
    toast = CONTEXT.get("toast")
    if toast:
        toast("Looking for it…")
    info = _screens_info()
    res = screen.look(cfg, f"Find this so the user can click it: {description}. Always give a target for it.",
                      CONTEXT["models"](), info.get("screens"), info.get("target", ""), bool(all_screens))
    if res.get("error"):
        return "Error: " + res["error"]
    tgt = res.get("target")
    if not tgt:
        return f"Error: I couldn't find {description!r} on the screen. Describe it differently or tell me where it is."
    mon = res.get("screen") or info.get("target", "")
    b = tgt["box"]
    if CONTEXT.get("pointer"):
        try:
            CONTEXT["pointer"](b, tgt["label"], 1.2 if action != "highlight_only" else float(cfg["pointer_seconds"]), mon)
        except Exception:
            pass
    if action == "highlight_only":
        return f"Highlighted {tgt['label']!r}."
    time.sleep(1.0)                                   # let the user see what is about to be clicked
    try:
        bad = _move_pointer(info, mon, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        if bad:
            return "Error: " + bad
        CONTROLLER.click("right" if action == "right_click" else "left", 2 if action == "double_click" else 1)
    except InputError as e:
        return "Error: " + str(e)
    time.sleep(0.25)
    return f"Clicked {tgt['label']!r}" + (f" on monitor {mon}." if len(info.get("screens") or []) > 1 else ".")


@tool("click_at",
      "Click at an exact place on a monitor, given as fractions 0-1 (x across, y down). Prefer click_element; use this only "
      "when you already know the position.",
      {"x": {"type": "number"}, "y": {"type": "number"},
       "monitor": {"type": "string", "description": "Monitor name; default = the one under the mouse"},
       "button": {"type": "string", "enum": ["left", "right", "middle"]}, "double": {"type": "boolean"}},
      ("x", "y"), confirm=True,
      describe=lambda a: f"{a.get('button') or 'left'}-click at ({a.get('x')}, {a.get('y')})")
def click_at(x: float, y: float, monitor: str = "", button: str = "left", double: bool = False) -> str:
    from .inputctl import CONTROLLER, InputError
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return "Error: x and y must be between 0 and 1."
    info = _screens_info()
    try:
        bad = _move_pointer(info, monitor or info.get("target", ""), x, y)
        if bad:
            return "Error: " + bad
        CONTROLLER.click(button, 2 if double else 1)
    except InputError as e:
        return "Error: " + str(e)
    return "Clicked."


@tool("type_text",
      "Type text into whatever has keyboard focus (click the field first with click_element). Use to dictate into a "
      "text box, a document, a search field.",
      {"text": {"type": "string"},
       "press_enter": {"type": "boolean", "description": "Press Enter afterwards (e.g. to submit a search)."}},
      ("text",), confirm=True,
      describe=lambda a: "type: " + str(a.get("text"))[:80] + ("  + Enter" if a.get("press_enter") else ""))
def type_text(text: str, press_enter: bool = False) -> str:
    from .inputctl import CONTROLLER, InputError
    cfg = CONTEXT["cfg"]
    try:
        method = str(cfg["type_method"]) if cfg is not None else "paste"
        if method == "keys":
            CONTROLLER.type_keys(text)
        else:
            CONTROLLER.type_paste(text)
        if press_enter:
            time.sleep(0.1)
            CONTROLLER.press("enter")
    except InputError as e:
        return "Error: " + str(e)
    return f"Typed {len(text)} characters."


@tool("press_keys",
      "Press a key or shortcut, e.g. 'enter', 'esc', 'ctrl+s', 'alt+f4', 'ctrl+shift+t', 'super'.",
      {"keys": {"type": "string"}}, ("keys",), confirm=True,
      describe=lambda a: f"press {a.get('keys')}")
def press_keys(keys: str) -> str:
    from .inputctl import CONTROLLER, InputError
    try:
        CONTROLLER.press(keys)
    except InputError as e:
        return "Error: " + str(e)
    return f"Pressed {keys}."


@tool("scroll_mouse", "Scroll the window under the mouse. Positive amount scrolls up, negative scrolls down.",
      {"amount": {"type": "integer", "description": "Wheel clicks, e.g. -5 to scroll down a page"}}, ("amount",))
def scroll_mouse(amount: int) -> str:
    from .inputctl import CONTROLLER, InputError
    try:
        CONTROLLER.scroll(int(amount))
    except InputError as e:
        return "Error: " + str(e)
    return "Scrolled."
