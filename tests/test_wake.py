import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aura.wake import match_wake
from aura.voice import resample

P = ["hey aura", "ok aura", "aura"]

def test_wake_match():
    assert match_wake("Hey Aura, open Firefox", P) == (True, "open firefox")
    assert match_wake("hey aura", P) == (True, "")
    assert match_wake("OK aura what time is it?", P) == (True, "what time is it")
    assert match_wake("aura volume down", P) == (True, "volume down")
    assert match_wake("what is the weather", P)[0] is False
    assert match_wake("hey siri open firefox", P)[0] is False
    assert match_wake("", P) == (False, "")
    print("ok wake matching")

def test_resample():
    x = np.sin(np.linspace(0, 20, 960)).astype(np.float32)
    assert len(resample(x, 48000, 16000)) == 320
    assert len(resample(x[:441], 44100, 16000)) == 160
    assert len(resample(x, 16000, 16000)) == 960
    assert len(resample(x[:240], 24000, 48000)) == 480
    print("ok resample")

if __name__ == "__main__":
    test_wake_match(); test_resample(); print("ALL OK")
