"""Place the overlay windows under KDE Plasma/Wayland.

Wayland clients can't position themselves or force "always on top". KWin can, so we load a tiny KWin
script (over D-Bus) that watches for our windows by title and puts them where we want.
"""
from __future__ import annotations

import logging

from .config import DATA_DIR

log = logging.getLogger("aura.kwin")
PLUGIN = "aura-windows"
BLOB_W, BLOB_H = 300, 520              # must match Blob.qml

SCRIPT = r"""
(function () {
var BLOB = "Aura Blob", CHAT = "Aura Quick Chat";
var FX = @FX@, FY = @FY@, MARGIN = @MARGIN@, SCREEN = "@SCREEN@";
function log(m) { try { print("aura-kwin: " + m); } catch (e) {} }
function workArea() {
    var out = workspace.activeScreen;
    if (SCREEN !== "") {
        try {
            var list = workspace.screens;
            for (var i = 0; i < list.length; i++) { if (list[i].name === SCREEN) { out = list[i]; break; } }
        } catch (e0) {}
    }
    try { return workspace.clientArea(KWin.MaximizeArea, out, workspace.currentDesktop); } catch (e) {}
    try { return out.geometry; } catch (e2) {}
    return {x: 0, y: 0, width: 1920, height: 1080};
}
function flags(w) {
    try { w.keepAbove = true; } catch (e) {}
    try { w.skipTaskbar = true; } catch (e) {}
    try { w.skipPager = true; } catch (e) {}
    try { w.skipSwitcher = true; } catch (e) {}
}
function place(w) {
    var a = workArea(), g = w.frameGeometry, x, y;
    if (w.caption === BLOB) {
        x = Math.round(a.x + MARGIN + FX * Math.max(0, a.width - g.width - 2 * MARGIN));
        y = Math.round(a.y + MARGIN + FY * Math.max(0, a.height - g.height - 2 * MARGIN));
    } else {
        x = a.x + Math.round((a.width - g.width) / 2);
        y = a.y + Math.round(a.height * 0.14);
    }
    g.x = x; g.y = y;
    w.frameGeometry = g;
}
function blobTarget(w) {
    var a = workArea(), g = w.frameGeometry;
    return {x: Math.round(a.x + MARGIN + FX * Math.max(0, a.width - g.width - 2 * MARGIN)),
            y: Math.round(a.y + MARGIN + FY * Math.max(0, a.height - g.height - 2 * MARGIN))};
}
function keepBlobPlaced(w) {            // re-apply whenever KWin moves/resizes it (it may be shown again later)
    var n = 0;
    function fix() {
        if (w.width <= 1 || n > 40) return;
        var t = blobTarget(w), g = w.frameGeometry;
        if (Math.abs(g.x - t.x) > 1 || Math.abs(g.y - t.y) > 1) {
            n++; g.x = t.x; g.y = t.y; w.frameGeometry = g;
            log("moved blob to " + t.x + "," + t.y + " (now at " + w.frameGeometry.x + "," + w.frameGeometry.y + ")");
        }
    }
    w.frameGeometryChanged.connect(fix);
    fix();
}
function focus(w) { if (w.caption === CHAT) { try { workspace.activeWindow = w; } catch (e) {} } }
var seen = {};
function setup(w) {
    if (!w) return;
    if (w.caption !== BLOB && w.caption !== CHAT) {
        // Wayland clients may set their title *after* the window appears: look again when it changes.
        if (!w.__auraWatch) {
            w.__auraWatch = true;
            try { w.captionChanged.connect(function () { setup(w); }); } catch (e) {}
        }
        return;
    }
    if (w.__auraDone) return;
    w.__auraDone = true;
    log("matched window '" + w.caption + "' size " + w.width + "x" + w.height);
    flags(w);
    if (w.caption === BLOB) { return; }        // position comes from a KWin window rule (see kde.set_blob_rule)
    place(w);
    focus(w);
    var done = false;
    w.frameGeometryChanged.connect(function () {
        if (done || w.width <= 1) return;
        done = true;
        place(w);
        focus(w);
    });
}
log("script loaded: fx=" + FX + " fy=" + FY + " margin=" + MARGIN + " screen='" + SCREEN + "'");
workspace.windowAdded.connect(setup);
try {                                    // windows that already exist when the script (re)loads, e.g. after Apply
    var existing = workspace.windowList();
    for (var i = 0; i < existing.length; i++) setup(existing[i]);
} catch (e) {}
})();
"""


def _clamp(v, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return default


def render(fx: float, fy: float, margin: int, screen: str = "") -> str:
    screen = "".join(ch for ch in str(screen) if ch.isalnum() or ch in "-_. :")
    return (SCRIPT.replace("@FX@", repr(_clamp(fx, 1.0))).replace("@FY@", repr(_clamp(fy, 0.0)))
            .replace("@MARGIN@", str(int(margin))).replace("@SCREEN@", screen))


def install(fx: float = 1.0, fy: float = 0.0, margin: int = 24, screen: str = "") -> bool:
    """(Re)load the KWin script. Returns False when KWin scripting isn't reachable (not KDE, no D-Bus...)."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
        path = DATA_DIR / "kwin" / "aura-windows.js"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(fx, fy, margin, screen))

        bus = QDBusConnection.sessionBus()
        scripting = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
        if not scripting.isValid():
            log.warning("KWin scripting interface not available; overlay placement disabled")
            return False
        scripting.call("unloadScript", PLUGIN)
        reply = scripting.call("loadScript", str(path), PLUGIN)
        args = reply.arguments()
        sid = int(args[0]) if args else -1
        if sid < 0:
            log.warning("KWin refused to load the script (%s)", reply.errorMessage())
            return False
        script = QDBusInterface("org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", bus)
        ok = script.isValid() and script.call("run").type() != QDBusMessage.MessageType.ErrorMessage
        if not ok:
            scripting.call("start")
        log.info("KWin placement script loaded (id %s, pos %.2f/%.2f)", sid, fx, fy)
        return True
    except Exception:
        log.exception("could not install KWin script")
        return False


def unload() -> None:
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
        QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                       QDBusConnection.sessionBus()).call("unloadScript", PLUGIN)
    except Exception:
        pass
