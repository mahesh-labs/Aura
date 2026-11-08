"""Meta (Super/Windows) key: a tap keeps doing what KDE does (opens the launcher), holding it opens voice mode.

We only *listen* to the keyboards (python-evdev, read-only), we never grab them, so KDE still sees every key.
Needs read access to /dev/input/event* (add yourself to the `input` group, then log out and in again).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("aura.metakey")


class MetaHold:
    def __init__(self, on_hold: Callable[[], None], hold_s: float = 1.0):
        self.on_hold = on_hold
        self.hold_s = hold_s
        self.status = "stopped"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ui = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="metakey")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ internals
    def _keyboards(self, evdev):
        out = []
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
                keys = d.capabilities().get(evdev.ecodes.EV_KEY, [])
                if evdev.ecodes.KEY_LEFTMETA in keys and evdev.ecodes.KEY_A in keys:
                    out.append(d)
                else:
                    d.close()
            except Exception:
                continue
        return out

    def _make_uinput(self, evdev):
        try:
            return evdev.UInput({evdev.ecodes.EV_KEY: [evdev.ecodes.KEY_F24]}, name="aura-metakey")
        except Exception:
            return None   # fine: the launcher may also open when you let go after a hold

    def _run(self) -> None:
        try:
            import evdev
            from evdev import ecodes
        except Exception:
            self.status = "python-evdev is not installed (pip install evdev)"
            log.warning("meta key: %s", self.status)
            return
        import selectors
        warned = False
        while not self._stop.is_set():
            devs = self._keyboards(evdev)
            if not devs:
                if not warned:
                    self.status = "no readable keyboard: add yourself to the 'input' group and log in again"
                    log.warning("meta key: %s", self.status)
                    warned = True
                self._stop.wait(5)
                continue
            warned = False
            self.status = f"listening on {len(devs)} keyboard(s)"
            log.info("meta key hold: %s", self.status)
            self._ui = self._make_uinput(evdev)
            sel = selectors.DefaultSelector()
            for d in devs:
                sel.register(d, selectors.EVENT_READ)
            timer: threading.Timer | None = None
            down_since = 0.0
            fired = False
            try:
                while not self._stop.is_set():
                    for key, _ in sel.select(timeout=0.5):
                        try:
                            events = list(key.fileobj.read())
                        except OSError:
                            raise
                        for ev in events:
                            if ev.type != ecodes.EV_KEY:
                                continue
                            if ev.code in (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA):
                                if ev.value == 1:
                                    down_since, fired = time.monotonic(), False
                                    if timer:
                                        timer.cancel()
                                    timer = threading.Timer(self.hold_s, self._fire)
                                    timer.daemon = True
                                    timer.start()
                                elif ev.value == 0 and timer:
                                    timer.cancel()
                                    timer = None
                            elif ev.value == 1 and timer:
                                timer.cancel()          # Meta+something else: a normal shortcut, not a hold
                                timer = None
            except OSError:
                log.info("keyboard went away; rescanning")
            finally:
                if timer:
                    timer.cancel()
                for d in devs:
                    try:
                        sel.unregister(d)
                        d.close()
                    except Exception:
                        pass
                if self._ui:
                    try:
                        self._ui.close()
                    except Exception:
                        pass
                    self._ui = None
        self.status = "stopped"

    def _fire(self) -> None:
        log.info("meta key held: voice")
        ui = self._ui
        if ui is not None:
            try:                       # a key pressed while Meta is down turns it into a shortcut, so
                from evdev import ecodes   # KDE does not open the launcher when you let go
                ui.write(ecodes.EV_KEY, ecodes.KEY_F24, 1)
                ui.write(ecodes.EV_KEY, ecodes.KEY_F24, 0)
                ui.syn()
            except Exception:
                pass
        try:
            self.on_hold()
        except Exception:
            log.exception("meta hold action failed")
