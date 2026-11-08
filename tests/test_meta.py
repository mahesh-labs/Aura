import sys, time, types, threading
sys.path.insert(0, ".")
from aura.metakey import MetaHold
from aura.config import Config
import tempfile, pathlib, json

# no evdev installed -> clear status, no crash
sys.modules.pop("evdev", None)
m = MetaHold(lambda: None); m._run()
assert "evdev" in m.status; print("ok missing evdev")

# fake evdev: press Meta, hold, release
ecodes = types.SimpleNamespace(EV_KEY=1, KEY_LEFTMETA=125, KEY_RIGHTMETA=126, KEY_A=30, KEY_F24=194)
class Ev:
    def __init__(s, c, v): s.type, s.code, s.value = 1, c, v
class Dev:
    def __init__(s, script): s.script = script; s.fd_r, s.fd_w = __import__("os").pipe()
    def capabilities(s): return {1: [125, 30]}
    def fileno(s): return s.fd_r
    def read(s):
        __import__("os").read(s.fd_r, 10); return iter(s.script.pop(0))
    def close(s): pass
dev = Dev([[Ev(125, 1)], [Ev(125, 0)], [Ev(125, 1)], [Ev(30, 1)], [Ev(125, 0)], [Ev(125, 1)]])
fake = types.SimpleNamespace(ecodes=ecodes, list_devices=lambda: ["x"], InputDevice=lambda p: dev, UInput=None)
fake.UInput = lambda *a, **k: (_ for _ in ()).throw(OSError())
sys.modules["evdev"] = fake; sys.modules["evdev.ecodes"] = ecodes
fired = []
m = MetaHold(lambda: fired.append(1), hold_s=0.3); m.start()
import os
def poke(): os.write(dev.fd_w, b"x"); time.sleep(0.05)
poke(); poke()            # tap: press + release
time.sleep(0.4); assert not fired
poke(); poke(); poke()    # Meta+A then release: combo
time.sleep(0.4); assert not fired
poke(); time.sleep(0.5)   # real hold
assert fired == [1], fired
m.stop(); print("ok meta tap / combo / hold")

d = pathlib.Path(tempfile.mkdtemp()); c = Config(d / "c.json"); c.set("model", "a"); c.set("model", "b")
(d / "c.json").write_text("{bad"); c2 = Config(d / "c.json"); assert c2["model"] == "a"; print("ok config backup")
print("ALL OK")
