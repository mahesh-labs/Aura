import sys, types, tempfile, pathlib
sys.path.insert(0, ".")
from aura import inputctl, tools
from aura.config import Config

ec = types.SimpleNamespace(EV_KEY=1, EV_REL=2, EV_ABS=3, ABS_X=0, ABS_Y=1, BTN_LEFT=272, BTN_RIGHT=273, BTN_MIDDLE=274,
                           REL_WHEEL=8, REL_HWHEEL=6, KEY_LEFTCTRL=29, KEY_LEFTSHIFT=42, KEY_LEFTMETA=125, KEY_LEFTALT=56,
                           KEY_S=31, KEY_A=30, KEY_V=47, KEY_ENTER=28, KEY_1=2, KEY_TAB=15, KEY_F4=62, KEY_SPACE=57,
                           KEY_H=35, KEY_I=23, KEY_COMMA=51, KEY_ESC=1, KEY_T=20)
log = []
class UI:
    def __init__(s, cap, name=""): s.name = name; log.append(("open", name))
    def write(s, t, c, v): log.append((s.name, t, c, v))
    def syn(s): pass
    def close(s): pass
fake = types.SimpleNamespace(ecodes=ec, UInput=UI, AbsInfo=lambda *a: a)
inputctl.os.access = lambda p, m: True
c = inputctl.Controller(); c._ev = fake
inputctl.time.sleep = lambda s: None

assert inputctl.key_codes("ctrl+shift+t", ec) == [29, 42, 20] and inputctl.key_codes("Enter", ec) == [28]
for bad in ("", "ctrl+unknownkey"):
    try: inputctl.key_codes(bad, ec); raise SystemExit("should fail")
    except inputctl.InputError: pass
print("ok key names")

c.move_to(0.5, 0.25, steps=4)
xs = [e for e in log if len(e) == 4 and e[1] == 3 and e[2] == 0]; ys = [e for e in log if len(e) == 4 and e[1] == 3 and e[2] == 1]
assert xs[-1][3] == round(0.5 * 65535) and ys[-1][3] == round(0.25 * 65535) and len(xs) == 4
c.click("left", 2)
assert [e for e in log if len(e) == 4 and e[2] == 272].__len__() == 4          # 2 x (down, up)
c.press("ctrl+s")
assert ("aura-keyboard", 1, 29, 1) in log and ("aura-keyboard", 1, 31, 1) in log and ("aura-keyboard", 1, 29, 0) in log
log.clear(); c.type_keys("Hi, 1")
downs = [e[2] for e in log if len(e) == 4 and e[0] == "aura-keyboard" and e[3] == 1]
assert 35 in downs and 23 in downs and 51 in downs and 57 in downs and 2 in downs and downs[0] == 42          # shift for 'H'
print("ok move / click / press / type")

# desktop mapping with two monitors side by side (second one is 2560 wide, first 1920)
info = {"screens": [{"name": "A", "x": 0, "y": 0, "w": 1920, "h": 1080}, {"name": "B", "x": 1920, "y": 0, "w": 2560, "h": 1440}]}
fx, fy = tools._desktop_fraction(info, "B", 0.5, 0.5)
assert abs(fx - (1920 + 1280) / 4480) < 1e-9 and abs(fy - 720 / 1440) < 1e-9
fx, fy = tools._desktop_fraction(info, "A", 0, 0); assert (fx, fy) == (0, 0)
print("ok multi-monitor coordinates")

# click_element end to end with fakes
cfg = Config(pathlib.Path(tempfile.mkdtemp()) / "c.json")
moves = []
class FakeCtl:
    def move_to(s, fx, fy): moves.append(("move", round(fx, 4), round(fy, 4)))
    def goto(s, x, y, bounds): moves.append(("goto", round(x), round(y), bounds)); return {"ok": True, "error": 0, "measured": (round(x), round(y))}
    def click(s, b="left", n=1): moves.append(("click", b, n))
    def press(s, k): moves.append(("press", k))
    def type_paste(s, t): moves.append(("paste", t))
    def type_keys(s, t): moves.append(("keys", t))
    def scroll(s, n): moves.append(("scroll", n))
inputctl.CONTROLLER = FakeCtl()
from aura import screen
shown = []
tools.CONTEXT.update(cfg=cfg, models=lambda: [], screens=lambda: dict(info, target="B"),
                     pointer=lambda box, label, secs, scr="": shown.append((box, label, scr)), toast=None)
tools.time.sleep = lambda s: None
from aura import cursor as _cur
_cur.available = lambda: False
screen.look = lambda *a, **k: {"answer": "x", "screen": "B", "target": {"label": "Close button", "box": [0.9, 0.0, 1.0, 0.1]}}
out = tools.click_element("the close button")
assert out.startswith("Clicked") and moves[-2][0] == "goto" and moves[-1] == ("click", "left", 1) and shown[0][2] == "B", (out, moves)
assert moves[-2][1:3] == (round(1920 + 0.95 * 2560), round(0.05 * 1440)) and moves[-2][3] == (0, 0, 4480, 1440), moves[-2]
assert tools.click_element("x", "highlight_only").startswith("Highlighted") and moves[-1] == ("click", "left", 1)
screen.look = lambda *a, **k: {"answer": "x", "screen": "B", "target": None}
assert tools.click_element("ghost").startswith("Error: I couldn't find")
assert tools.type_text("hello", True) == "Typed 5 characters." and moves[-2:] == [("paste", "hello"), ("press", "enter")]
cfg.set("type_method", "keys"); tools.type_text("yo"); assert moves[-1] == ("keys", "yo")
assert tools.press_keys("ctrl+s").startswith("Pressed") and tools.scroll_mouse(-3) == "Scrolled." and moves[-1] == ("scroll", -3)
assert all(tools.REGISTRY.get(n).confirm for n in ("click_element", "click_at", "type_text", "press_keys"))
print("ok click_element / type_text / press_keys tools (ask first by default)"); print("ALL OK")


# --- closed loop: the compositor maps the virtual mouse onto only the FIRST monitor (a worst case); goto must still arrive
inputctl.CONTROLLER = None
from aura import cursor
c2 = inputctl.Controller(); c2._ev = fake
c2._pos = (0, 0)
state = {"x": 0, "y": 0}
def fake_move(fx, fy, steps=10):
    state["x"] = round(fx * 1920); state["y"] = round(fy * 1080)       # device only covers the 1920x1080 first monitor
c2.move_to = fake_move
cursor.available = lambda: True
cursor.query = lambda timeout=2.5: {"x": state["x"], "y": state["y"], "screens": []}
r = c2.goto(1000, 500, (0, 0, 4480, 1440))
assert r["ok"] and abs(state["x"] - 1000) <= 3 and abs(state["y"] - 500) <= 3, (r, state)
r = c2.goto(3200, 720, (0, 0, 4480, 1440))                              # unreachable: must report a miss, not lie
assert not r["ok"] and r["measured"] is not None, r
cursor.query = lambda timeout=2.5: None
assert c2.goto(10, 10, (0, 0, 100, 100))["measured"] is None            # no feedback -> open loop, no crash
print("ok closed-loop pointer placement"); print("ALL OK")
