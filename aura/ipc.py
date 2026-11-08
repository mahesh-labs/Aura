"""Tiny client for the running daemon (plain sockets, no Qt import => instant hotkey response)."""
from __future__ import annotations

import socket

from .config import SOCKET_PATH


def send(cmd: str, timeout: float = 1.5) -> str | None:
    """Send a command to the running daemon. Returns its reply, or None if no daemon is listening."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(SOCKET_PATH))
        s.sendall((cmd.strip() + "\n").encode())
        try:
            return s.recv(4096).decode().strip() or "ok"
        except socket.timeout:
            return "ok"
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return None
    finally:
        s.close()
