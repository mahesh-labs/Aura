"""`aura` command-line entry point.

Kept dependency-free for the hot path (hotkey commands) so a key press costs ~30 ms:
Qt is only imported by `aura start`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time

from .config import CONFIG_PATH, DATA_DIR, LOG_PATH, MODELS_DIR, SOCKET_PATH


def send(cmd: str, timeout: float = 3.0) -> str | None:
    """Send a command to the running daemon; None if it is not running."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(SOCKET_PATH))
        s.sendall((cmd + "\n").encode())
        return s.recv(1024).decode().strip()
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
        return None
    finally:
        s.close()


def start_detached() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "aura", "start", "--background"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_daemon(wait: float = 25.0) -> bool:
    if send("ping", 1.0) == "pong":
        return True
    start_detached()
    end = time.time() + wait
    while time.time() < end:
        time.sleep(0.4)
        if send("ping", 1.0) == "pong":
            return True
    return False


def cmd_control(name: str) -> int:
    if not ensure_daemon():
        print("Aura could not be started. Run `aura start` in a terminal to see why.", file=sys.stderr)
        return 1
    reply = send(name)
    if reply != "ok" and name != "status":
        print(reply or "no reply", file=sys.stderr)
        return 1
    if name == "status":
        print(reply)
    return 0


def cmd_start(background: bool, show: bool, debug: bool) -> int:
    if send("ping", 1.0) == "pong":
        if show:
            send("show")
        print("Aura is already running.")
        return 0
    try:
        from .app import run
    except ImportError as e:
        print(f"Missing dependency: {e}\nRun the install script, or `pip install PySide6-Essentials`.", file=sys.stderr)
        return 1
    return run(show_main=show or not background, debug=debug)


def cmd_ask(text: str) -> int:
    """Terminal chat with the same agent/tools (no Qt needed): handy for debugging."""
    import threading

    from .controller import Controller

    done = threading.Event()
    ctrl: Controller

    def on_event(e: dict) -> None:
        t = e["type"]
        if t == "delta":
            print(e["text"], end="", flush=True)
        elif t == "tool_start":
            print(f"\n  [tool] {e['summary']}", flush=True)
        elif t == "tool_end":
            print(f"  [{e['status']}] {e['result'][:200]}", flush=True)
        elif t == "confirm":
            ans = input(f"\n  Allow: {e['summary']} ? [y/N] ").strip().lower()
            ctrl.answer_confirm(e["id"], ans in ("y", "yes"))
        elif t == "error":
            print(f"\n  error: {e['text']}", file=sys.stderr)
        elif t == "state" and e["state"] == "idle":
            done.set()

    ctrl = Controller(emit=on_event)
    ctrl.send_text(text)
    done.wait(600)
    print()
    return 0


def cmd_setup() -> int:
    from . import kde

    for f in kde.install_files():
        print("installed", f)
    print("\nAutostart is enabled: Aura starts in the background when you log in.")
    print("Window rules are written when the app starts (run `aura start` once).\n")
    print(kde.SHORTCUT_HELP)
    return 0


def cmd_uninstall() -> int:
    from . import kde

    send("quit", 1.0)
    kde.uninstall_files()
    print("Removed desktop entries, autostart and KWin rules. Your chats and settings are kept in", DATA_DIR)
    return 0


def cmd_doctor() -> int:
    from . import kde
    from .config import Config
    from .llm import OllamaClient

    cfg = Config()
    ok = True

    def check(label: str, good: bool, hint: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"{'✓' if good else '✗'} {label}" + (f"  → {hint}" if hint and not good else ""))

    print(f"Config: {CONFIG_PATH}\nLog:    {LOG_PATH}\n")
    check("Wayland/KDE session",
          os.environ.get("XDG_SESSION_TYPE") == "wayland" and "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", ""),
          "overlay placement relies on KWin; other desktops need their own window rules")
    client = OllamaClient(cfg)
    models = client.list_models()
    check(f"Ollama reachable ({len(models)} models)", bool(models), "run `ollama serve`")
    if models:
        check(f"chat model {cfg['model']} is installed", cfg["model"] in models, f"ollama pull {cfg['model']} or change it in Settings")
        from . import screen
        vm = screen.vision_model(cfg, models)
        check(f"vision model for screen help: {vm}", bool(vm), "ollama pull gemma3:12b, or pick one in Settings")
    for mod, hint in (("PySide6", "pip install PySide6"), ("numpy", ""), ("sounddevice", "install portaudio"),
                      ("faster_whisper", "pip install faster-whisper"), ("kokoro_onnx", "pip install kokoro-onnx"),
                      ("evdev", "pip install evdev (Meta key + mouse/keyboard control)"),
                      ("PIL", "pip install pillow (screen reading)"), ("cv2", "pip install opencv-python-headless (icon pointing)"),
                      ("mcp", "pip install mcp (only needed for MCP servers)")):
        try:
            __import__(mod)
            check(f"python: {mod}", True)
        except (ImportError, OSError):
            check(f"python: {mod}", False, hint)
    for exe, pkg in (("parec", "libpulse"), ("pactl", "libpulse"), ("wpctl", "pipewire"), ("playerctl", "playerctl"),
                     ("wl-copy", "wl-clipboard"), ("notify-send", "libnotify"), ("spectacle", "spectacle"),
                     ("tesseract", "tesseract tesseract-data-eng (accurate pointing)"), ("busctl", "systemd"),
                     ("kwriteconfig6", "kde-cli-tools / kconfig"), ("espeak-ng", "espeak-ng")):
        check(f"tool: {exe}", shutil.which(exe) is not None, f"pacman -S {pkg}")
    check("Kokoro voice model files", (MODELS_DIR / "kokoro-v1.0.onnx").is_file() and (MODELS_DIR / "voices-v1.0.bin").is_file(),
          "run install.sh again (downloads them), or set tts_engine to espeak")
    check("/dev/uinput writable (mouse/keyboard control)", os.access("/dev/uinput", os.W_OK), "see aura/inputctl.py for the one-time setup")
    check("can read keyboards (Meta-key hold)", any(os.access(p, os.R_OK) for p in __import__("glob").glob("/dev/input/event*")),
          "sudo usermod -aG input $USER, then log out and in")
    check("KWin window rules installed", kde.rules_installed(), "start Aura once (`aura start`)")
    check("Aura daemon running", send("ping", 1.0) == "pong", "run `aura start`")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aura", description="Local voice + text AI assistant")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("start", help="run the background app")
    s.add_argument("--background", action="store_true", help="start hidden (tray only)")
    s.add_argument("--show", action="store_true", help="open the main window")
    s.add_argument("--debug", action="store_true")
    for name, helptext in (
        ("voice", "toggle voice mode (bind to a hotkey)"),
        ("chat", "toggle the quick chat box (bind to a hotkey)"),
        ("show", "open the main window"),
        ("toggle", "show/hide the main window"),
        ("cancel", "stop whatever Aura is doing"),
        ("point-test", "show the pointer overlay once (test)"),
        ("look-test", "screenshot + vision model + pointer (test)"),
        ("status", "print the current state"),
        ("quit", "quit the background app"),
    ):
        sub.add_parser(name, help=helptext)
    a = sub.add_parser("ask", help="one-shot question in the terminal")
    a.add_argument("text", nargs="+")
    sub.add_parser("setup", help="install desktop entry + autostart")
    sub.add_parser("uninstall", help="remove desktop entry, autostart and KWin rules")
    sub.add_parser("doctor", help="check that everything is set up")

    args = p.parse_args(argv)
    if args.cmd in (None, "start"):
        return cmd_start(getattr(args, "background", False), getattr(args, "show", args.cmd is None),
                         getattr(args, "debug", False))
    if args.cmd in ("voice", "chat", "show", "toggle", "cancel", "status", "quit"):
        if args.cmd == "quit" and send("ping", 1.0) != "pong":
            return 0
        return cmd_control(args.cmd)
    if args.cmd == "ask":
        return cmd_ask(" ".join(args.text))
    if args.cmd == "setup":
        return cmd_setup()
    if args.cmd == "uninstall":
        return cmd_uninstall()
    if args.cmd == "doctor":
        return cmd_doctor()
    return 0


if __name__ == "__main__":
    sys.exit(main())
