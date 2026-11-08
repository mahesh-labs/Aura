"""`./run.sh models` : finds out which combination of native libraries crashes (each test runs in its own process)."""
from __future__ import annotations

import subprocess
import sys

PRE = "import sys, logging; logging.basicConfig(level=logging.WARNING); from aura.config import Config; c = Config(); from aura import voice\n"
STT = "voice.STT(c).load(); print('  whisper loaded', flush=True)\n"
KOK = "voice.KokoroEngine(c); print('  kokoro loaded', flush=True)\n"
QT = "from PySide6.QtWidgets import QApplication; app = QApplication(sys.argv[:1]); print('  qt started', flush=True)\n"
THREAD = ("import threading\n"
          "def go():\n"
          "    voice.STT(c).load(); print('  whisper loaded', flush=True)\n"
          "    voice.KokoroEngine(c); print('  kokoro loaded', flush=True)\n"
          "t = threading.Thread(target=go); t.start(); t.join()\n")

OUT = ("o, fs, ch = voice.open_output(c, 24000); import numpy as np; o.write(np.zeros((2400, ch), 'float32')); "
       "print('  speaker opened + wrote', fs, ch, flush=True)\n")
INP = "m, fs2 = voice.open_input(c, lambda *a: None); print('  mic opened', fs2, flush=True)\n"
LOAD = STT + KOK

CASES = [
    ("S1 speaker only", PRE + OUT),
    ("S2 mic, then speaker", PRE + INP + OUT),
    ("S3 speaker, then mic", PRE + OUT + INP),
    ("S4 Qt, then speaker", PRE + QT + OUT),
    ("S5 Qt + whisper, then speaker", PRE + QT + STT + OUT),
    ("S6 Qt + whisper + kokoro, then speaker", PRE + QT + STT + KOK + OUT),
    ("S7 Qt + whisper + kokoro, then mic, then speaker", PRE + QT + STT + KOK + INP + OUT),
    ("A  whisper, then kokoro (plain python)", PRE + STT + KOK),
    ("B  kokoro, then whisper (plain python)", PRE + KOK + STT),
    ("C  Qt first, then whisper, then kokoro", PRE + QT + STT + KOK),
    ("D  Qt first, loaded in a background thread (what Aura does)", PRE + QT + THREAD),
]


def main() -> int:
    for name, code in CASES:
        print(f"\n[{name}]", flush=True)
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        print(p.stdout.rstrip())
        if p.returncode == 0:
            print("  -> OK")
        else:
            print(f"  -> FAILED (exit {p.returncode}{' = crashed by a signal' if p.returncode < 0 else ''})")
            tail = [ln for ln in (p.stderr or "").strip().splitlines() if ln.strip()][-3:]
            for ln in tail:
                print("    ", ln[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
