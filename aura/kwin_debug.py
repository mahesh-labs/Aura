"""`./run.sh kwin` : prints everything needed to find out why the blob is not where it should be."""
from __future__ import annotations

import shutil
import subprocess

from .config import Config, DATA_DIR


def _run(*cmd: str) -> str:
    if not shutil.which(cmd[0]):
        return f"(no {cmd[0]})"
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=10)
        return (p.stdout + p.stderr).strip() or "(empty)"
    except Exception as e:
        return f"(failed: {e})"


def main() -> int:
    cfg = Config()
    print("== settings ==")
    for k in ("blob_fx", "blob_fy", "blob_screen", "blob_margin", "blob_corner"):
        print(f"  {k} = {cfg[k]!r}")
    print("\n== forced KDE window rules (these override any script) ==")
    rules = _run("kreadconfig6", "--file", "kwinrulesrc", "--group", "General", "--key", "rules")
    print("  rules =", rules)
    for g in [r for r in rules.split(",") if r.strip() and not r.startswith("(")]:
        desc = _run("kreadconfig6", "--file", "kwinrulesrc", "--group", g, "--key", "Description")
        pos = _run("kreadconfig6", "--file", "kwinrulesrc", "--group", g, "--key", "position")
        print(f"  {g}: {desc!r} position={pos!r}")
    print("\n== placement script ==")
    path = DATA_DIR / "kwin" / "aura-windows.js"
    print("  file:", path, "exists" if path.exists() else "MISSING")
    for q in ("qdbus6", "qdbus"):
        if shutil.which(q):
            print("  loaded in KWin:", _run(q, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.isScriptLoaded", "aura-windows"))
            break
    print("  KWin:", _run("kwin_wayland", "--version"))
    print("\n== what the script logged (open voice mode first, then run this) ==")
    out = _run("journalctl", "--user", "-b", "--no-pager", "-g", "aura-kwin")
    print("\n".join(out.splitlines()[-25:]) or "(nothing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
