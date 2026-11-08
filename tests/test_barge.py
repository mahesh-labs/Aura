import sys, threading, queue, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aura.voice import VoiceController
from aura.config import Config
import tempfile

class TTS:
    def __init__(s): s._pending = 1; s.muted = False; s.stopped = 0
    def stop(s): s.stopped += 1

def run(levels, pending=1):
    vc = VoiceController.__new__(VoiceController)
    vc.cfg = Config(Path(tempfile.mkdtemp()) / "c.json"); vc.tts = TTS(); vc.tts._pending = pending
    vc._ms = type("M", (), {"q": queue.Queue()})()
    for a in levels:
        vc._ms.q.put(np.full(320, a, dtype=np.float32))
    cancel, tcancel, done, out = threading.Event(), threading.Event(), threading.Event(), {}
    t = threading.Thread(target=vc._barge_watch, args=(cancel, tcancel, done, out)); t.start()
    time.sleep(0.8); done.set(); t.join(2)
    return vc, tcancel, out

vc, tc, out = run([0.01] * 20 + [0.2] * 12)
assert tc.is_set() and vc.tts.muted and vc.tts.stopped == 1 and len(out["prefix"]) >= 10
vc, tc, out = run([0.01] * 40)                       # own voice at low level: no interrupt
assert not tc.is_set()
vc, tc, out = run([0.2] * 30, pending=0)             # not speaking: ignored
assert not tc.is_set()
vc, tc, out = run([0.2] * 5 + [0.01] * 5 + [0.2] * 5)  # short bursts
assert not tc.is_set()
print("ok barge-in watcher"); print("ALL OK")
