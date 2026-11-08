"""Audio device fallback + wake listener flow, using a fake `sounddevice` (no hardware needed)."""
import sys, types, threading, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

class PAErr(Exception): pass
calls = []
class FakeStream:
    def __init__(self, kind, **kw):
        calls.append((kind, kw.get("samplerate"), kw.get("channels"), kw.get("device")))
        if kw["samplerate"] == 16000 or kw["device"] is None:       # mimic: ALSA default can't do 16k / default dev missing
            raise PAErr("Unanticipated host error -9999")
        self.cb, self.kw, self.run = kw.get("callback"), kw, False
    def start(self):
        self.run = True
        if self.cb:
            def feed():
                fs = self.kw["samplerate"]; n = int(fs * 0.02); t = 0
                while self.run:
                    x = (0.002 * np.random.randn(n, self.kw["channels"])).astype(np.float32)
                    if 1.0 < (t % 4.0) < 2.2: x += (0.1 * np.sin(2*np.pi*200*(np.arange(n)+t*fs)/fs))[:, None].astype(np.float32)
                    self.cb(x, n, None, None); t += 0.02; time.sleep(0.002)
            threading.Thread(target=feed, daemon=True).start()
    def stop(self): self.run = False
    def close(self): pass
    def write(self, x): pass
fake = types.SimpleNamespace(
    InputStream=lambda **kw: FakeStream("in", **kw), OutputStream=lambda **kw: FakeStream("out", **kw),
    query_devices=lambda dev=None, kind=None: ([{"name": "hw:0", "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000},
                                                 {"name": "pipewire", "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000}]
                                                if dev is None and kind is None else {"default_samplerate": 48000}),
    default=types.SimpleNamespace(device=[None, None]))
sys.modules["sounddevice"] = fake

from aura.config import Config
from aura.voice import Mic, open_input, _pick_device, collect_utterance
from aura.wake import WakeListener

def test_device_fallback_and_resample():
    cfg = Config(Path("/tmp/aura_t.json"))
    assert _pick_device("", "input") == 1                       # prefers 'pipewire'
    stream, fs = open_input(cfg, lambda *a: None); stream.stop()
    assert fs == 48000, fs                                      # 16k failed -> device default rate
    a = Mic(cfg).utterance(lambda: False, lambda v: None, 6.0)
    assert a is not None and 1.0 < len(a) / 16000 < 3.5, None if a is None else len(a)/16000
    print("ok mic fallback 16k->48k + resample, utterance", round(len(a)/16000, 2), "s")

def test_wake_flow():
    cfg = Config(Path("/tmp/aura_t.json")); cfg.set("wake_phrases", "hey aura, aura", save=False)
    started = []
    class V:
        active = False
        def start(self, initial_text=None): started.append(initial_text); self.active = True
    w = WakeListener(cfg, Mic(cfg), V(), lambda m: print("toast", m))
    heard = iter(["we should buy milk", "Hey Aura, open Firefox"])
    w.stt.load = lambda: None; w.stt.transcribe = lambda audio, prompt=None: next(heard)
    w._stop.clear(); w._thread = threading.current_thread()
    r = w._listen_until_wake()
    assert r is None or r == "open firefox" or r == "" , r
    print("ok wake flow returned", repr(r))


def test_pulse_backend_with_fake_tools():
    """parec/pacat replaced by tiny scripts: checks the mic delivers blocks and the speaker writes the bytes."""
    import os, stat, sys, tempfile, time, pathlib
    import numpy as np
    d = pathlib.Path(tempfile.mkdtemp())
    py = sys.executable
    (d / "parec").write_text(f"#!{py}\nimport sys, time, numpy as np\nsys.stdout = sys.stdout.buffer\n"
                             "t = np.arange(320) / 16000\nwhile True:\n    sys.stdout.write((0.5*np.sin(2*np.pi*440*t)).astype('float32').tobytes()); sys.stdout.flush(); time.sleep(0.02)\n")
    out_file = d / "played.raw"
    (d / "pacat").write_text(f"#!{py}\nimport sys\nopen({str(out_file)!r}, 'wb').write(sys.stdin.buffer.read())\n")
    (d / "pactl").write_text(f"#!{py}\nprint('1\\talsa_input.usb-mic\\tx\\ty\\tz\\n2\\talsa_output.speakers.monitor\\tx\\ty\\tz', end='')\n")
    for n in ("parec", "pacat", "pactl"):
        (d / n).chmod(0o755)
    old = os.environ["PATH"]; os.environ["PATH"] = f"{d}:{old}"
    try:
        from aura import audio_pulse, voice
        from aura.config import Config
        cfg = Config(d / "c.json")
        assert audio_pulse.available() and voice.use_pulse(cfg)
        assert voice.list_devices("input") == ["alsa_input.usb-mic"], voice.list_devices("input")
        got = []
        st, fs = voice.open_input(cfg, lambda a, n, t, s: got.append(a))
        assert fs == 16000
        time.sleep(0.5); st.stop(); st.close()
        assert len(got) >= 5 and got[0].shape == (320, 1) and abs(got[3]).max() > 0.4, len(got)
        out, ofs, ch = voice.open_output(cfg, 24000)
        out.write(np.full(2400, 0.25, dtype="float32")); out.write(np.full(2400, 0.25, dtype="float32")); out.close()
        raw = np.frombuffer(out_file.read_bytes(), dtype=np.float32)
        assert ofs == 24000 and ch == 1 and len(raw) == 2400 * 2 and abs(raw[-1] - 0.25) < 1e-6, len(raw)   # +120 ms lead-in
        cfg.set("audio_backend", "portaudio"); assert not voice.use_pulse(cfg)
    finally:
        os.environ["PATH"] = old
    print("ok pulse backend (parec/pacat)")

if __name__ == "__main__":
    test_device_fallback_and_resample(); test_wake_flow(); test_pulse_backend_with_fake_tools(); print("ALL OK")
