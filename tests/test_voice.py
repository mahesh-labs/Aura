import sys, threading, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aura.voice import collect_utterance, parse_yes_no, TTSPlayer, SR_IN, BLOCK
from aura.config import Config

rng = np.random.default_rng(0)
def noise(sec, amp=0.003): return rng.normal(0, amp, int(SR_IN*sec)).astype(np.float32)
def tone(sec, amp=0.1): t=np.arange(int(SR_IN*sec))/SR_IN; return (amp*np.sin(2*np.pi*180*t)*(1+0.3*np.sin(2*np.pi*3*t))).astype(np.float32)
def blocks(sig): return (sig[i:i+BLOCK] for i in range(0, len(sig)-BLOCK, BLOCK))

def test_vad_basic():
    sig = np.concatenate([noise(0.6), tone(1.2), noise(1.5)])
    levels=[]
    a = collect_utterance(blocks(sig), on_level=levels.append)
    assert a is not None and 1.2 <= len(a)/SR_IN <= 2.6, len(a)/SR_IN
    assert max(levels) > 0.3
    print("ok vad utterance", round(len(a)/SR_IN,2), "s")

def test_vad_silence_and_click():
    assert collect_utterance(blocks(noise(3.0)), wait_s=1.5) is None
    sig = np.concatenate([noise(0.5), tone(0.07), noise(1.2), tone(1.0), noise(1.5)])   # click then real speech
    a = collect_utterance(blocks(sig))
    assert a is not None and len(a)/SR_IN > 0.9
    print("ok vad ignores click, silence returns None")

def test_vad_loud_start_and_stop():
    sig = np.concatenate([tone(1.0, 0.2), noise(1.5)])        # speaking from the very first block
    a = collect_utterance(blocks(sig)); assert a is not None
    ev = {"s": False}
    assert collect_utterance(blocks(np.concatenate([noise(.5), tone(5)])), stop=lambda: True) is None
    print("ok vad immediate speech / stop")

def test_yes_no():
    assert parse_yes_no("Yes, go ahead") is True and parse_yes_no("no don't") is False
    assert parse_yes_no("hmm what") is None and parse_yes_no("no, yes") is False
    print("ok yes/no")

def test_tts_player_queue_logic():
    cfg = Config(Path("/tmp/x_aura.json")); started=[]; levels=[]
    p = TTSPlayer(cfg, levels.append, lambda: started.append(1), lambda m: started.append(m))
    class Fake:
        def synth(self, t): time.sleep(0.05); return np.zeros(2400, np.float32), 24000
    p._engine = Fake(); p._engine_key = (cfg["tts_engine"], cfg["tts_voice"])
    # no audio device in CI: replace player loop with a fake that just consumes
    def fake_play():
        while True:
            gen, audio, sr = p._audio_q.get()
            if gen != p._gen: p._done_one(); continue
            p.on_start(); time.sleep(0.05); p._done_one()
    p._started = True
    threading.Thread(target=p._synth_loop, daemon=True).start(); threading.Thread(target=fake_play, daemon=True).start()
    for s in ["a", "b", "c"]: p.speak(s)
    p.wait_idle(timeout=5); assert p._pending == 0 and len(started) == 3, (p._pending, started)
    for s in ["a"]*6: p.speak(s)
    p.stop(); p.wait_idle(timeout=5); assert p._pending == 0
    print("ok tts queue/stop accounting")


def test_classify_reply():
    from aura.voice import classify_reply
    assert classify_reply("yes") is True and classify_reply("no thanks") is False
    assert classify_reply("") is None
    r = classify_reply("don't delete it, just list the folder")
    assert isinstance(r, str) and "list the folder" in r
    print("ok classify_reply")



def test_sound_does_not_count_as_speech():
    import numpy as np, time, aura.voice as v, tempfile, pathlib
    writes = []
    class Out:
        def write(self, a): time.sleep(0.002); writes.append(float(np.abs(a).max()))
        def stop(self): pass
        def close(self): pass
    v.open_output = lambda cfg, sr: (Out(), sr, 1)
    from aura.config import Config
    started = []
    t = v.TTSPlayer(Config(pathlib.Path(tempfile.mkdtemp()) / "c.json"), lambda x: None, lambda: started.append(1), lambda m: None)
    t.play_sound(np.full(4800, 0.4, dtype="float32"), 24000)
    time.sleep(0.6)
    assert max(writes) > 0.3 and not started and t._pending == 0
    t.stop(); t.play_sound(np.full(2400, 0.4, dtype="float32"), 24000); n = len(writes); time.sleep(0.4)
    assert len(writes) > n                                                     # stop() does not cancel sounds
    print("ok sounds bypass speech accounting")




if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f()
    print("ALL OK")
