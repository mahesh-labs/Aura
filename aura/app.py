"""Daemon: QApplication, QML windows, tray icon, single-instance lock and the IPC server."""
from __future__ import annotations

import fcntl
import logging
import os
import signal
import sys
from pathlib import Path

from .config import LOCK_PATH, LOG_PATH, SOCKET_PATH, ensure_dirs

QML_DIR = Path(__file__).parent / "ui" / "qml"


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(LOG_PATH))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


def _make_icon():
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QRadialGradient
    pm = QPixmap(128, 128)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QRadialGradient(QPointF(48, 44), 80)
    g.setColorAt(0.0, QColor("#9fe9ff"))
    g.setColorAt(0.55, QColor("#7b6cff"))
    g.setColorAt(1.0, QColor("#c04bff"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawEllipse(14, 14, 100, 100)
    p.end()
    return QIcon(pm)


_crash_file = None


def run(initial_cmd: str | None) -> int:
    ensure_dirs()
    _setup_logging()
    log = logging.getLogger("aura")

    # single instance: whoever holds the lock is the daemon
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        from .ipc import send
        import time
        for _ in range(20):                       # the other instance may still be starting
            if send(initial_cmd or "show") is not None:
                return 0
            time.sleep(0.25)
        log.error("another instance holds the lock but is not answering")
        return 1

    try:                                   # if a native library crashes, leave a Python traceback next to the log
        import faulthandler
        from .config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        global _crash_file
        _crash_file = open(DATA_DIR / "crash.log", "a")
        faulthandler.enable(_crash_file, all_threads=True)
    except Exception:
        pass
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")      # steadier than threaded on NVIDIA/Wayland (avoids title-bar flicker)
    from PySide6.QtCore import QTimer, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QAction
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from . import kwin
    from .backend import Backend

    qInstallMessageHandler(lambda mode, ctx, msg: log.info("qt: %s", msg))
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Aura")
    app.setDesktopFileName("aura")
    app.setQuitOnLastWindowClosed(False)
    icon = _make_icon()
    app.setWindowIcon(icon)

    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda ws: [log.warning("qml: %s", w.toString()) for w in ws])
    engine.rootContext().setContextProperty("backend", backend)
    for name in ("Main.qml", "QuickChat.qml", "Blob.qml", "Pointer.qml"):
        engine.load(QUrl.fromLocalFile(str(QML_DIR / name)))
    roots = {o.objectName(): o for o in engine.rootObjects()}
    if not {"main", "chat", "blob", "pointer"} <= roots.keys():
        log.error("QML failed to load (see warnings above); got %s", list(roots))
        return 1
    backend.win = roots

    # ---- tray
    tray = QSystemTrayIcon(icon, app)
    menu = QMenu()
    for label, cmd in (("Open Aura", "show"), ("Voice mode", "voice"), ("Quick chat", "chat"),
                       ("New chat", "new-chat")):
        act = QAction(label, menu)
        act.triggered.connect(lambda _=False, c=cmd: backend.handle_command(c))
        menu.addAction(act)
    wake_act = QAction("Wake word (“hey aura”)", menu)
    wake_act.setCheckable(True)
    wake_act.setChecked(bool(backend.cfg["wake_enabled"]))
    wake_act.triggered.connect(lambda on: backend.setSetting("wake_enabled", bool(on)))
    backend.wakeChanged.connect(lambda: wake_act.setChecked(backend.wake.running))
    menu.addAction(wake_act)
    menu.addSeparator()
    quit_act = QAction("Quit", menu)
    quit_act.triggered.connect(app.quit)
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.setToolTip("Aura")
    tray.activated.connect(lambda reason: backend.handle_command("show")
                           if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
    tray.show()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("no system tray available; use `aura show` to open the window")

    # ---- IPC server (hotkeys call `aura voice` etc.)
    QLocalServer.removeServer(str(SOCKET_PATH))
    server = QLocalServer(app)
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(str(SOCKET_PATH)):
        log.error("cannot listen on %s: %s", SOCKET_PATH, server.errorString())
        return 1
    live = []

    def on_conn():
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()
            live.append(sock)

            def read(s=sock):
                cmd = bytes(s.readAll()).decode(errors="ignore").strip()
                if not cmd:
                    return
                try:
                    reply = backend.handle_command(cmd)
                except Exception as e:
                    log.exception("command failed: %s", cmd)
                    reply = f"error: {e}"
                s.write((reply + "\n").encode())
                s.flush()
                s.disconnectFromServer()

            sock.readyRead.connect(read)
            sock.disconnected.connect(lambda s=sock: (live.remove(s) if s in live else None, s.deleteLater()))

    server.newConnection.connect(on_conn)

    quitting = {"on": False}

    def quit_now(*_):
        """Hide every window first (so the blob can never linger), stop worker threads, then exit.
        A watchdog guarantees the process ends even if an audio/model thread is slow to stop."""
        if quitting["on"]:
            return
        quitting["on"] = True
        for name in ("blob", "chat", "main"):
            try:
                roots[name].setVisible(False)
            except Exception:
                pass
        try:
            tray.hide()
        except Exception:
            pass
        kwin.unload()
        backend.shutdown()
        import threading as _t
        wd = _t.Timer(2.5, lambda: os._exit(0))
        wd.daemon = True
        wd.start()
        app.quit()

    backend.quit_cb = quit_now
    quit_act.triggered.disconnect()
    quit_act.triggered.connect(quit_now)
    app.aboutToQuit.connect(quit_now)
    signal.signal(signal.SIGINT, quit_now)
    signal.signal(signal.SIGTERM, quit_now)
    keepalive = QTimer()                          # lets Python handle signals while Qt runs
    keepalive.start(500)
    keepalive.timeout.connect(lambda: None)

    # ---- placement + warm-up + first command
    QTimer.singleShot(200, backend.applyWindowRules)
    if backend.cfg["preload_models"]:
        QTimer.singleShot(1500, backend.voice.preload)
    if backend.cfg["wake_enabled"]:
        QTimer.singleShot(3000, backend.wake.start)
    import threading as _th
    _th.Thread(target=backend.mcp.start, daemon=True, name="mcp-start").start()
    if backend.cfg["meta_hold_enabled"]:
        QTimer.singleShot(2000, backend.meta.start)
    if initial_cmd:
        QTimer.singleShot(500, lambda: backend.handle_command(initial_cmd))
    log.info("Aura is running (model %s)", backend.cfg["model"])
    return app.exec()
