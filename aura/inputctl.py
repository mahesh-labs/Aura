"""Mouse and keyboard control through a virtual input device (/dev/uinput). Works on Wayland.

Needs write access to /dev/uinput. One-time setup (then log out and in):
    echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/99-uinput.rules
    echo uinput | sudo tee /etc/modules-load.d/uinput.conf
    sudo modprobe uinput && sudo udevadm control --reload && sudo udevadm trigger
    sudo usermod -aG input $USER
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

log = logging.getLogger("aura.input")

SETUP_HELP = ("Aura can't create a virtual mouse/keyboard: it needs write access to /dev/uinput. "
              "Run once: echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\", OPTIONS+=\"static_node=uinput\"' | "
              "sudo tee /etc/udev/rules.d/99-uinput.rules; echo uinput | sudo tee /etc/modules-load.d/uinput.conf; "
              "sudo modprobe uinput; sudo udevadm control --reload; sudo udevadm trigger; "
              "sudo usermod -aG input $USER  - then log out and back in.")

ABS_MAX = 65535
_US_SHIFT = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
             "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/", "~": "`"}
_PLAIN = {" ": "SPACE", "-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE", "\\": "BACKSLASH", ";": "SEMICOLON",
          "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH", "`": "GRAVE", "\n": "ENTER", "\t": "TAB"}
_NAMES = {"enter": "ENTER", "return": "ENTER", "tab": "TAB", "esc": "ESC", "escape": "ESC", "space": "SPACE",
          "backspace": "BACKSPACE", "delete": "DELETE", "del": "DELETE", "up": "UP", "down": "DOWN", "left": "LEFT",
          "right": "RIGHT", "home": "HOME", "end": "END", "pageup": "PAGEUP", "pagedown": "PAGEDOWN",
          "ctrl": "LEFTCTRL", "control": "LEFTCTRL", "alt": "LEFTALT", "shift": "LEFTSHIFT", "super": "LEFTMETA",
          "meta": "LEFTMETA", "win": "LEFTMETA", "insert": "INSERT", "menu": "COMPOSE", "print": "SYSRQ"}


class InputError(Exception):
    pass


def key_codes(spec: str, ecodes) -> list[int]:
    """'ctrl+shift+t' -> [KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_T]."""
    out = []
    for part in [p.strip().lower() for p in spec.replace(" ", "+").split("+") if p.strip()]:
        name = _NAMES.get(part)
        if name is None:
            if len(part) == 1 and part.isalnum():
                name = part.upper()
            elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
                name = part.upper()
            else:
                raise InputError(f"unknown key {part!r}")
        code = getattr(ecodes, "KEY_" + name, None)
        if code is None:
            raise InputError(f"unknown key {part!r}")
        out.append(code)
    if not out:
        raise InputError("no keys given")
    return out


class Controller:
    def __init__(self):
        self._lock = threading.RLock()
        self._mouse = None
        self._kbd = None
        self._ev = None

    # ---------------------------------------------------------------- setup
    def _evdev(self):
        if self._ev is None:
            try:
                import evdev
                self._ev = evdev
            except Exception:
                raise InputError("python-evdev is not installed (uv pip install evdev).")
        return self._ev

    def _devices(self):
        ev = self._evdev()
        ec = ev.ecodes
        if self._mouse is None:
            if not os.access("/dev/uinput", os.W_OK):
                raise InputError(SETUP_HELP)
            try:
                cap_m = {ec.EV_KEY: [ec.BTN_LEFT, ec.BTN_RIGHT, ec.BTN_MIDDLE],
                         ec.EV_REL: [ec.REL_WHEEL, ec.REL_HWHEEL],
                         ec.EV_ABS: [(ec.ABS_X, ev.AbsInfo(0, 0, ABS_MAX, 0, 0, 0)),
                                     (ec.ABS_Y, ev.AbsInfo(0, 0, ABS_MAX, 0, 0, 0))]}
                self._mouse = ev.UInput(cap_m, name="aura-pointer")
                keys = [v for k, v in vars(ec).items() if k.startswith("KEY_") and isinstance(v, int) and v < 249]
                self._kbd = ev.UInput({ec.EV_KEY: sorted(set(keys))}, name="aura-keyboard")
            except Exception as e:
                self._mouse = self._kbd = None
                raise InputError(f"couldn't create the virtual input device ({e}). " + SETUP_HELP)
            time.sleep(0.7)                    # the compositor needs a moment to notice new devices
        return self._mouse, self._kbd, ec

    def close(self) -> None:
        for d in (self._mouse, self._kbd):
            try:
                if d:
                    d.close()
            except Exception:
                pass
        self._mouse = self._kbd = None

    # ---------------------------------------------------------------- mouse
    def move_to(self, fx: float, fy: float, steps: int = 10) -> None:
        """fx, fy: position in the whole desktop as fractions 0..1 (0,0 = top-left of the leftmost/topmost monitor)."""
        with self._lock:
            m, _, ec = self._devices()
            fx, fy = min(1.0, max(0.0, fx)), min(1.0, max(0.0, fy))
            tx, ty = round(fx * ABS_MAX), round(fy * ABS_MAX)
            cx, cy = getattr(self, "_pos", (tx, ty))
            for i in range(1, steps + 1):                      # glide, so hover effects and tooltips register
                x, y = cx + (tx - cx) * i / steps, cy + (ty - cy) * i / steps
                m.write(ec.EV_ABS, ec.ABS_X, round(x))
                m.write(ec.EV_ABS, ec.ABS_Y, round(y))
                m.syn()
                time.sleep(0.012)
            self._pos = (tx, ty)
            time.sleep(0.05)

    def goto(self, x: float, y: float, bounds: tuple[float, float, float, float], tol: int = 3) -> dict:
        """Move the pointer to logical pixel (x, y) and verify it arrived, correcting if it didn't.

        bounds = (left, top, width, height) of the whole desktop in logical pixels. Where the compositor can tell us
        the real pointer position (KWin), we measure and correct; otherwise this is a single open-loop move.
        Returns {"ok": bool, "error": px or None, "measured": (x, y) or None}.
        """
        from . import cursor
        ux, uy, uw, uh = bounds
        fx, fy = (x - ux) / uw, (y - uy) / uh
        measured = None
        prev = None
        sx, sy = float(uw), float(uh)                      # logical px per unit fraction (secant estimate)
        for attempt in range(4):
            self.move_to(fx, fy)
            q = cursor.query() if cursor.available() else None
            if not q:
                return {"ok": True, "error": None, "measured": None}
            measured = (q["x"], q["y"])
            ex, ey = x - measured[0], y - measured[1]
            if abs(ex) <= tol and abs(ey) <= tol:
                return {"ok": True, "error": max(abs(ex), abs(ey)), "measured": measured}
            if prev is not None:
                dfx, dfy = fx - prev[0], fy - prev[1]
                if abs(dfx) > 1e-5 and abs(measured[0] - prev[2]) > 0:
                    sx = (measured[0] - prev[2]) / dfx
                if abs(dfy) > 1e-5 and abs(measured[1] - prev[3]) > 0:
                    sy = (measured[1] - prev[3]) / dfy
            prev = (fx, fy, measured[0], measured[1])
            fx += ex / (sx if abs(sx) > 1 else uw)
            fy += ey / (sy if abs(sy) > 1 else uh)
            fx, fy = min(1.0, max(0.0, fx)), min(1.0, max(0.0, fy))
        err = max(abs(x - measured[0]), abs(y - measured[1])) if measured else None
        return {"ok": err is not None and err <= 12, "error": err, "measured": measured}

    def click(self, button: str = "left", count: int = 1) -> None:
        with self._lock:
            m, _, ec = self._devices()
            code = {"left": ec.BTN_LEFT, "right": ec.BTN_RIGHT, "middle": ec.BTN_MIDDLE}.get(button)
            if code is None:
                raise InputError("button must be left, right or middle")
            for _ in range(max(1, count)):
                m.write(ec.EV_KEY, code, 1)
                m.syn()
                time.sleep(0.04)
                m.write(ec.EV_KEY, code, 0)
                m.syn()
                time.sleep(0.07)

    def scroll(self, clicks: int) -> None:
        """Positive = up, negative = down."""
        with self._lock:
            m, _, ec = self._devices()
            for _ in range(abs(int(clicks))):
                m.write(ec.EV_REL, ec.REL_WHEEL, 1 if clicks > 0 else -1)
                m.syn()
                time.sleep(0.03)

    # ---------------------------------------------------------------- keyboard
    def press(self, spec: str) -> None:
        with self._lock:
            _, k, ec = self._devices()
            codes = key_codes(spec, ec)
            for c in codes:
                k.write(ec.EV_KEY, c, 1)
                k.syn()
                time.sleep(0.01)
            time.sleep(0.03)
            for c in reversed(codes):
                k.write(ec.EV_KEY, c, 0)
                k.syn()
                time.sleep(0.01)

    def type_keys(self, text: str, delay: float = 0.012) -> None:
        """Type with key events (assumes a US layout). Characters without a key are skipped; returns nothing."""
        with self._lock:
            _, k, ec = self._devices()
            for ch in text:
                shift = ch.isupper() or ch in _US_SHIFT
                base = _US_SHIFT.get(ch, ch).lower() if ch not in _PLAIN else ch
                name = _PLAIN.get(base) or (base.upper() if base.isalnum() and base.isascii() else None)
                code = getattr(ec, "KEY_" + name, None) if name else None
                if code is None:
                    continue
                if shift:
                    k.write(ec.EV_KEY, ec.KEY_LEFTSHIFT, 1)
                    k.syn()
                k.write(ec.EV_KEY, code, 1)
                k.syn()
                k.write(ec.EV_KEY, code, 0)
                k.syn()
                if shift:
                    k.write(ec.EV_KEY, ec.KEY_LEFTSHIFT, 0)
                    k.syn()
                time.sleep(delay)

    def type_paste(self, text: str) -> None:
        """Layout-independent typing: put the text on the clipboard, press Ctrl+V, restore the clipboard."""
        if not (shutil.which("wl-copy") and shutil.which("wl-paste")):
            raise InputError("wl-clipboard is not installed (sudo pacman -S wl-clipboard), or set type_method to keys.")
        old = None
        try:
            r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=3)
            old = r.stdout if r.returncode == 0 else None
        except Exception:
            old = None
        subprocess.run(["wl-copy"], input=text.encode(), timeout=5)
        time.sleep(0.08)
        self.press("ctrl+v")
        time.sleep(0.35)
        if old is not None:
            subprocess.run(["wl-copy"], input=old, timeout=5)


CONTROLLER = Controller()
