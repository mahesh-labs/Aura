"""Ask KWin where the mouse pointer really is (the only reliable way on Wayland), and what its monitors are.

A tiny KWin script prints the position to the journal; we load it with busctl and read the line back.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

log = logging.getLogger("aura.cursor")

SCRIPT = """
(function () {
var p = workspace.cursorPos;
print("aura-cursor @TOKEN@ " + Math.round(p.x) + " " + Math.round(p.y));
try {
  var s = workspace.screens;
  for (var i = 0; i < s.length; i++) {
    var g = s[i].geometry;
    print("aura-cursor-screen @TOKEN@ " + s[i].name + " " + g.x + " " + g.y + " " + g.width + " " + g.height);
  }
} catch (e) {}
})();
"""


def available() -> bool:
    return bool(shutil.which("busctl") and shutil.which("journalctl"))


def _busctl(*args: str) -> str:
    r = subprocess.run(["busctl", "--user", *args], capture_output=True, text=True, timeout=5)
    return (r.stdout or "") + (r.stderr or "")


def query(timeout: float = 2.5) -> dict | None:
    """{"x": int, "y": int, "screens": [{"name","x","y","w","h"}]} in KWin's logical pixels, or None."""
    if not available():
        return None
    token = uuid.uuid4().hex[:10]
    name = "aura-cursor-" + token
    with tempfile.TemporaryDirectory(prefix="aura-cur-") as d:
        path = Path(d) / "c.js"
        path.write_text(SCRIPT.replace("@TOKEN@", token))
        try:
            out = _busctl("call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", str(path), name)
            parts = out.split()
            sid = int(parts[1]) if len(parts) >= 2 and parts[0] == "i" else -1
            if sid < 0:
                return None
            _busctl("call", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
        except Exception as e:
            log.debug("cursor query failed: %s", e)
            return None
        res = None
        end = time.time() + timeout
        while time.time() < end and res is None:
            time.sleep(0.06)
            try:
                lines = subprocess.run(["journalctl", "--user", "-b", "--no-pager", "-o", "cat", "-n", "60", "-g", token],
                                       capture_output=True, text=True, timeout=3).stdout.splitlines()
            except Exception:
                continue
            cur, screens = None, []
            for ln in lines:
                if "aura-cursor-screen " + token in ln:
                    t = ln.split(token, 1)[1].split()
                    if len(t) >= 5:
                        try:
                            screens.append({"name": " ".join(t[:-4]), "x": int(t[-4]), "y": int(t[-3]),
                                            "w": int(t[-2]), "h": int(t[-1])})
                        except ValueError:
                            pass
                elif "aura-cursor " + token in ln:
                    t = ln.split(token, 1)[1].split()
                    if len(t) >= 2:
                        try:
                            cur = (int(t[0]), int(t[1]))
                        except ValueError:
                            pass
            if cur:
                res = {"x": cur[0], "y": cur[1], "screens": screens}
        try:
            _busctl("call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", name)
        except Exception:
            pass
        return res
