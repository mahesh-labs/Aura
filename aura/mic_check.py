"""`./run.sh mic` : which microphone actually delivers sound? Records 4 s from every input and prints the loudness."""
from __future__ import annotations

import shutil
import subprocess
import sys

import numpy as np


def run(*cmd: str, timeout: float = 5) -> str:
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except Exception as e:
        return f"(failed: {e})"


def record(device: str | None, seconds: float = 4.0) -> tuple[int, float, str]:
    cmd = ["parec", "--raw", "--format=float32le", "--rate=16000", "--channels=1", "--latency-msec=100"]
    if device:
        cmd.append(f"--device={device}")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = p.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        p.terminate()
        out, err = p.communicate()
    arr = np.frombuffer(out[: len(out) // 4 * 4], dtype=np.float32)
    return len(out), float(np.abs(arr).max()) if arr.size else 0.0, err.decode(errors="ignore").strip()


def main() -> int:
    for tool in ("parec", "pacat", "pactl"):
        print(f"{tool:6} ->", shutil.which(tool) or "NOT INSTALLED (sudo pacman -S --needed libpulse)")
    if not shutil.which("parec"):
        return 1
    print("\ndefault source:", run("pactl", "get-default-source"))
    print("default sink  :", run("pactl", "get-default-sink"))
    print("\nrecording 4 s from each input - SPEAK NOW, keep talking until it finishes\n")
    rows = [ln.split("\t") for ln in run("pactl", "list", "short", "sources").splitlines() if "\t" in ln]
    for r in [None] + [x[1] for x in rows if not x[1].endswith(".monitor")]:
        n, peak, err = record(r)
        label = "(default)" if r is None else r
        state = next((x[-1] for x in rows if len(x) > 1 and x[1] == r), "")
        verdict = "NO DATA" if n == 0 else ("silent" if peak < 0.003 else "SOUND OK")
        print(f"  {label:60} {state:10} bytes={n:7} peak={peak:.3f}  {verdict}")
        if err:
            print("     parec said:", err.splitlines()[-1][:160])
    print("\nTo force one, put its name in ~/.config/aura/config.json as \"input_device\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
