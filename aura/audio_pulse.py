"""Audio through the PulseAudio/PipeWire command-line tools (`parec` / `pacat` / `pactl`) instead of PortAudio.

PortAudio is a native library living inside the Aura process; on some systems it corrupts the heap and takes the
whole app down (glibc "malloc ... assertion failed"). parec/pacat run as separate processes, so a problem there can
never crash Aura, and they talk to PipeWire exactly like any other desktop app (via pipewire-pulse).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger("aura.pulse")


def available() -> bool:
    return bool(shutil.which("parec") and shutil.which("pacat"))


def list_devices(kind: str) -> list[str]:
    """Names of capture (kind='input') or playback (kind='output') devices."""
    if not shutil.which("pactl"):
        return []
    try:
        out = subprocess.run(["pactl", "list", "short", "sources" if kind == "input" else "sinks"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    names = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not parts[1].endswith(".monitor"):
            names.append(parts[1])
    return names


def default_source() -> str:
    try:
        return subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def resolve_input(name: str) -> str:
    """The source to record from. A Bluetooth headset mic is silent while the headset is in music (A2DP) mode,
    so when nothing was chosen explicitly and the default is a Bluetooth source, use a wired/USB/built-in one."""
    names = list_devices("input")
    if name and name in names:
        return name
    default = default_source()
    if False:  # the Bluetooth headset mic works (verified with ./run.sh mic); keep the system default
        other = [n for n in names if not n.startswith("bluez_input")]
        # a real microphone beats a line-in jack (which is usually unplugged and silent)
        other.sort(key=lambda n: (0 if "mic" in n.lower() else 2 if "line" in n.lower() else 1))
        if other and (default.startswith("bluez_input")):
            log.warning("default microphone %s is a Bluetooth headset; using %s instead", default, other[0])
            return other[0]
    return ""


def _device_arg(name: str, kind: str) -> list[str]:
    """--device=NAME only if NAME is a real pulse device (older settings may hold PortAudio names)."""
    if name and name in list_devices(kind):
        return [f"--device={name}"]
    return []


class PulseInput:
    """Microphone via `parec`: 16 kHz mono float32 blocks of 20 ms delivered to `callback`."""
    RATE = 16000

    def __init__(self, device: str, callback):
        cmd = ["parec", "--raw", "--format=float32le", f"--rate={self.RATE}", "--channels=1", "--latency-msec=100",
               "--client-name=Aura", "--stream-name=Aura microphone"] + _device_arg(resolve_input(device), "input")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.cb = callback
        threading.Thread(target=self._log_errors, daemon=True, name="parec-stderr").start()
        self._run = True
        self.t = threading.Thread(target=self._read, daemon=True, name="parec-reader")
        self.t.start()

    def _log_errors(self) -> None:
        try:
            for line in self.proc.stderr:
                log.warning("parec: %s", line.decode(errors="ignore").strip())
        except Exception:
            pass

    def _read(self) -> None:
        block = int(self.RATE * 0.02) * 4
        buf = b""
        f = self.proc.stdout
        while self._run:
            try:
                data = f.read(block - len(buf))
            except Exception:
                break
            if not data:
                break
            buf += data
            if len(buf) >= block:
                arr = np.frombuffer(buf[:block], dtype=np.float32).reshape(-1, 1).copy()
                buf = buf[block:]
                try:
                    self.cb(arr, arr.shape[0], None, None)
                except Exception:
                    log.exception("mic callback failed")

    def stop(self) -> None:
        self._run = False

    def close(self) -> None:
        self._run = False
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class PulseOutput:
    """Speakers via `pacat`. write() blocks like a normal audio stream because the pipe to pacat fills up."""

    def __init__(self, device: str, rate: int):
        cmd = ["pacat", "--playback", "--raw", "--format=float32le", f"--rate={int(rate)}", "--channels=1",
               "--latency-msec=80", "--client-name=Aura", "--stream-name=Aura voice"] + _device_arg(device, "output")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.rate = int(rate)
        self._last = time.time()
        self._lock = threading.Lock()
        self._open = True
        # Keep the stream fed with silence while idle: a Bluetooth/PipeWire sink that goes to sleep between
        # replies clips the first words and jumps in volume when it wakes. Silence costs nothing.
        threading.Thread(target=self._silence, daemon=True, name="pacat-silence").start()

    def _silence(self) -> None:
        chunk = np.zeros(int(self.rate * 0.05), dtype=np.float32).tobytes()
        while self._open:
            time.sleep(0.05)
            if time.time() - self._last < 0.12:
                continue
            if not self._lock.acquire(blocking=False):
                continue
            try:
                self.proc.stdin.write(chunk)
            except Exception:
                return
            finally:
                self._lock.release()

    def write(self, data: np.ndarray) -> None:
        x = np.ascontiguousarray(data, dtype=np.float32).reshape(-1)
        with self._lock:
            self.proc.stdin.write(x.tobytes())
            self._last = time.time()

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self._open = False
        try:
            self.proc.stdin.close()                 # pacat drains what is queued, then exits
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
