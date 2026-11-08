"""Command line: `aura [command]`. Used by autostart and by the global keyboard shortcuts."""
from __future__ import annotations

import sys

USAGE = """aura - local voice/text desktop assistant

usage: aura [command]
  show            open the main window (default)
  voice           toggle voice mode (floating blob)
  voice-start / voice-stop
  chat            toggle the quick chat box
  new-chat        start a fresh conversation
  wake / wake-on / wake-off   toggle the "hey aura" wake word
  quit            stop the background app
  doctor          check that everything is set up
  setup           (re)write the menu entry and autostart
  point-test      show the pointer overlay once
  look-test       screenshot + vision + pointer test
  status          print state of the running app
  --background    start the background app without showing a window (used at login)
"""
CMDS = {"show", "voice", "voice-start", "voice-stop", "chat", "chat-show", "chat-hide", "new-chat",
        "quit", "status", "ping", "wake", "wake-on", "wake-off", "point-test", "look-test"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "show"
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("doctor", "setup", "uninstall", "ask"):       # maintenance commands live in cli.py
        from .cli import main as cli_main
        return cli_main(argv)
    background = cmd in ("--background", "daemon")
    if not background and cmd not in CMDS:
        print(USAGE)
        return 2
    from .ipc import send
    reply = send("ping" if background else cmd)
    if reply is not None:           # a daemon is already running and handled it
        if not background:
            print(reply)
        return 0
    if cmd == "quit" or cmd == "status" or cmd == "ping":
        print("aura is not running")
        return 1
    from .app import run
    return run(None if background else cmd)


if __name__ == "__main__":
    sys.exit(main())
