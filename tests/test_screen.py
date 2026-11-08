import sys; sys.path.insert(0, ".")
from aura import screen, tools
from aura.config import Config
import tempfile, pathlib

r = screen.parse_reply('Sure! {"answer":"Click Save.","target":{"label":"Save button","box":[0.1,0.2,0.3,0.25]}} done')
assert r["answer"] == "Click Save." and r["target"]["box"] == [0.1, 0.2, 0.3, 0.25], r
r = screen.parse_reply('{"answer":"x","target":{"label":"a","box":[100,200,300,250]}}')      # 0..1000 scale
assert r["target"]["box"] == [0.1, 0.2, 0.3, 0.25], r
assert screen.parse_reply("just words")["target"] is None
assert screen.parse_reply('{"answer":"x","target":{"label":"a","box":[0.5,0.5,0.4,0.4]}}')["target"] is None
print("ok parse_reply")

cfg = Config(pathlib.Path(tempfile.mkdtemp()) / "c.json")
assert screen.vision_model(cfg, ["qwen3-coder:30b", "gemma3:12b"]) == "gemma3:12b"
assert screen.vision_model(cfg, ["qwen3-coder:30b"]) is None
cfg.set("vision_model", "foo"); assert screen.vision_model(cfg, []) == "foo"
cfg.set("vision_model", "")
print("ok model pick")

got = []
tools.CONTEXT.update(cfg=cfg, models=lambda: [], pointer=lambda box, label, secs, scr='': got.append((box, label, secs, scr)))
screen.look = lambda c, q, m, *a: {"answer": "Press the blue button.", "target": {"label": "Blue button", "box": [0.1, 0.1, 0.2, 0.2]}}
out = tools.look_at_screen("where?", True)
assert "highlighted" in out and got == [([0.1, 0.1, 0.2, 0.2], "Blue button", 3.0, "")], (out, got)
screen.look = lambda c, q, m, *a: {"error": "No vision model found."}
assert tools.look_at_screen("x").startswith("Error")
assert tools.point_at_screen_region(0.1, 0.1, 0.2, 0.2, "z") == "Highlighted."
assert tools.point_at_screen_region(0.5, 0.1, 0.2, 0.2).startswith("Error")
print("ok tools"); print("ALL OK")

import importlib; screen = importlib.reload(screen)
import types
from PIL import Image
calls = []
def fake_capture(p, *a):
    Image.new("RGB", (2000, 1000), "white").save(p); return True
screen.capture = fake_capture
cfg2 = Config(pathlib.Path(tempfile.mkdtemp()) / "d.json"); cfg2.set("vision_model", "gemma3:12b"); cfg2.set("model", "qwen3-coder:30b")
class R:
    def __init__(s, code, js): s.status_code, s._j, s.text = code, js, str(js)
    def json(s): return s._j
state = {"n": 0}
def fget(url, **k): return R(200, {"models": [{"name": "qwen3-coder:30b"}, {"name": "gemma3:12b"}]})
def fpost(url, json=None, **k):
    calls.append((url.rsplit("/", 1)[-1], json.get("model"), json.get("keep_alive"), (json.get("options") or {}).get("num_ctx")))
    if url.endswith("/chat"):
        state["n"] += 1
        if state["n"] == 1: return R(500, "cuda out of memory")
        return R(200, {"message": {"content": '{"answer":"ok","target":null}'}})
    return R(200, {})
screen.requests = types.SimpleNamespace(get=fget, post=fpost)
res = screen.look(cfg2, "q", [])
assert res.get("answer") == "ok", (res, calls)
assert ("generate", "qwen3-coder:30b", 0, None) in calls, calls          # chat model unloaded before the first try
assert [c for c in calls if c[0] == "chat"][1][3] == 3072, calls          # smaller context on retry
state["n"] = -5
screen.requests = types.SimpleNamespace(get=fget, post=lambda url, json=None, **k: R(500, "cuda out of memory"))
assert "GPU is full" in screen.look(cfg2, "q", [])["error"]
print("ok out-of-memory retry"); print("ALL OK")


# --- grid cells -> box, two-pass pointing, multi-monitor crop
assert screen.cells_to_box(["C4", "D4"], 12, 8) == [2/12, 3/8, 4/12, 4/8]
assert screen.cells_to_box(["Z9", "x"], 12, 8) is None and screen.cells_to_box([], 12, 8) is None
assert screen.cells_to_box(["a1"], 12, 8) == [0, 0, 1/12, 1/8]
screen = importlib.reload(screen)
screen.capture = fake_capture
screen.shutil = types.SimpleNamespace(which=lambda n: None)     # no tesseract -> grid method
screen._have_cv2 = lambda: False
replies = ['{"answer":"Click the green Play button.","target":{"text":"","description":"green play","region":"bottom-right"}}',
           '{"answer":"Click the green Play button.","target":{"label":"green Play button","cells":["J6","K6"]}}',
           '{"found": true, "cells": ["C4","D4"]}']
seen = []
def fpost2(url, json=None, **k):
    if url.endswith("/chat"):
        seen.append(json["messages"][0]["content"][:30])
        return R(200, {"message": {"content": replies[len(seen) - 1]}})
    return R(200, {})
screen.requests = types.SimpleNamespace(get=fget, post=fpost2)
res = screen.look(cfg2, "which button plays?", [])
b = res["target"]["box"]
# pass 1 box: x 9/12..11/12, y 5/8..6/8; zoom area = that +/- 0.6*size (min 1 cell), pass 2 cells C4-D4 of an 8x8 grid
x1 = 9/12 - max((2/12)*0.6, 1/12); w = min(1.0, 11/12 + max((2/12)*0.6, 1/12)) - x1
assert abs(b[0] - (x1 + 2/8*w)) < 1e-9 and len(seen) == 3 and res["answer"].startswith("Click"), (b, seen)
print("ok two-pass pointing")

# multi-monitor: two 1000x500 screens side by side; desktop picture is 2000x500 (scale 1); cut the right one
def two_screens_shot(cmds, path):
    im = Image.new("RGB", (2000, 500), "black"); im.paste(Image.new("RGB", (1000, 500), "red"), (1000, 0)); im.save(path); return True
screen = importlib.reload(screen); screen._run_shot = two_screens_shot
screen.shutil = types.SimpleNamespace(which=lambda n: "/x/" + n)
import pathlib as _p
pth = _p.Path(tempfile.mkdtemp()) / "s.png"
scr = [{"name": "A", "x": 0, "y": 0, "w": 1000, "h": 500}, {"name": "B", "x": 1000, "y": 0, "w": 1000, "h": 500}]
assert screen.capture(pth, scr, "B"); im = Image.open(pth); assert im.size == (1000, 500) and im.getpixel((5, 5)) == (255, 0, 0)
assert screen.capture(pth, scr, "A"); assert Image.open(pth).getpixel((5, 5)) == (0, 0, 0)
print("ok multi-monitor crop"); print("ALL OK")

# --- OCR text-anchored pointing (needs the tesseract CLI; skipped without it)
import shutil as _sh
if _sh.which("tesseract"):
    from PIL import ImageDraw, ImageFont
    screen = importlib.reload(screen)
    fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    im = Image.new("RGB", (1600, 900), (25, 25, 30)); d = ImageDraw.Draw(im)
    d.text((100, 700), "steam play now? no", fill=(220, 220, 220), font=fnt)               # terminal-like text
    d.rectangle([1200, 760, 1480, 840], fill=(60, 180, 60)); d.text((1270, 783), "PLAY", fill="white", font=fnt)   # green button
    d.text((100, 100), "Library  Store  Community", fill=(220, 220, 220), font=fnt)
    words = screen.ocr_words(im)
    assert any(w["text"].lower().startswith("librar") for w in words), [w["text"] for w in words]
    hits = screen.find_text(words, "Play")
    assert len(hits) == 2, hits
    xs = sorted(h["box"][0] for h in hits); assert xs[0] < 400 and xs[1] > 1200, xs
    assert len(screen.find_text(words, "community")) == 1 and screen.find_text(words, "zebra") == []
    print("ok OCR + text matching (both PLAY places found)")

    # full flow with a fake model: stage 1 names the text, stage 2 picks box number of the button
    screen.capture = lambda p, *a: (im.save(p), True)[1]
    cfg3 = Config(pathlib.Path(tempfile.mkdtemp()) / "e.json"); cfg3.set("vision_model", "gemma3:12b"); cfg3.set("model", "gemma3:12b")
    order = sorted(range(2), key=lambda i: 0)
    seen2 = []
    def fp(url, json=None, **k):
        if url.endswith("/chat"):
            seen2.append(json["messages"][0]["content"])
            if len(seen2) == 1:
                return R(200, {"message": {"content": '{"answer":"Click the green Play button.","target":{"text":"PLAY","description":"green button bottom right","region":"bottom-right"}}'}})
            return R(200, {"message": {"content": '{"id": 99}'}})               # invalid id -> region fallback
        return R(200, {})
    screen.requests = types.SimpleNamespace(get=fget, post=fp)
    res = screen.look(cfg3, "which button do I press to play?", [])
    b = res["target"]["box"]
    assert b[0] > 0.6 and b[1] > 0.75, res          # the green button on the right, not the terminal text
    print("ok text-anchored look picks the right PLAY")
print("ALL OK")


# --- icons / shapes: numbered candidate boxes (OpenCV)
try:
    import cv2
    have_cv = True
except Exception:
    have_cv = False
if have_cv:
    screen = importlib.reload(screen)
    from PIL import ImageDraw
    img = Image.new("RGB", (1600, 900), (30, 30, 36)); dr = ImageDraw.Draw(img)
    truth = {"gear": [200, 300, 260, 360], "star": [700, 120, 770, 190], "button": [1200, 760, 1480, 840], "toggle": [900, 500, 980, 540]}
    dr.ellipse(truth["gear"], outline=(230, 230, 230), width=5); dr.ellipse([218, 318, 242, 342], outline=(230, 230, 230), width=4)
    dr.polygon([(735, 120), (748, 160), (770, 160), (752, 175), (760, 190), (735, 178), (710, 190), (718, 175), (700, 160), (722, 160)], outline=(230, 230, 100), width=3)
    dr.rectangle(truth["button"], fill=(60, 180, 60)); dr.rounded_rectangle(truth["toggle"], 20, fill=(40, 120, 230))
    boxes = screen.ui_boxes(img)
    for name, t in truth.items():
        assert any(screen._iou(b, t) > 0.45 for b in boxes), (name, len(boxes))
    assert len(boxes) <= 60
    print("ok ui_boxes finds icons and coloured controls:", len(boxes), "candidates")

    screen.capture = lambda p, *a: (img.save(p), True)[1]
    screen.shutil = types.SimpleNamespace(which=lambda n: None)       # no tesseract -> icon path
    target_box = max(boxes, key=lambda b: screen._iou(b, truth["gear"]))
    idx = boxes.index(target_box) + 1
    n = {"i": 0}
    def fp3(url, json=None, **k):
        if url.endswith("/chat"):
            n["i"] += 1
            if n["i"] == 1:
                return R(200, {"message": {"content": '{"answer":"Click the gear icon.","target":{"text":"","description":"grey gear icon, left","region":"left"}}'}})
            return R(200, {"message": {"content": '{"id": %d}' % idx}})
        return R(200, {})
    screen.requests = types.SimpleNamespace(get=fget, post=fp3)
    res = screen.look(cfg3, "where are the settings?", [])
    bx = res["target"]["box"]; W_, H_ = 1600, 900
    px = [bx[0] * W_, bx[1] * H_, bx[2] * W_, bx[3] * H_]
    assert screen._iou(px, truth["gear"]) > 0.35, px
    print("ok icon pointing via numbered boxes")

    # all monitors: two screens, answers combined, highlight on the first screen that has a target
    screen = importlib.reload(screen)
    shots = {"A": Image.new("RGB", (800, 450), "black"), "B": Image.new("RGB", (800, 450), "white")}
    screen.grab_screens = lambda scr, names: [(n, shots[n]) for n in names]
    texts = iter(['{"answer":"A shows nothing.","target":null}', '{"answer":"B shows a page.","target":null}'])
    screen.requests = types.SimpleNamespace(get=fget, post=lambda url, json=None, **k: R(200, {"message": {"content": next(texts)}}) if url.endswith("/chat") else R(200, {}))
    res = screen.look(cfg3, "what is on my screens?", [], [{"name": "A", "x": 0, "y": 0, "w": 800, "h": 450}, {"name": "B", "x": 800, "y": 0, "w": 800, "h": 450}], "A", True)
    assert "On monitor A: A shows nothing." in res["answer"] and "On monitor B: B shows a page." in res["answer"], res
    print("ok all monitors combined")

# --- the model picks a REAL OCR line by id (no hallucinated text), narrowed to the quoted words
if _sh.which("tesseract"):
    from PIL import ImageDraw, ImageFont
    screen = importlib.reload(screen)
    fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    lg = Image.new("RGB", (1800, 700), (20, 20, 24)); d = ImageDraw.Draw(lg)
    rows = ["INFO faster_whisper: Processing audio", "INFO aura.screen: unloaded gemma4:latest to make room", "WARNING phonemizer: words count mismatch"]
    for i, t in enumerate(rows):
        d.text((60, 100 + i * 80), t, fill=(220, 220, 220), font=fnt)
    words = screen.ocr_words(lg); lines = screen.ocr_lines(words)
    want = next(l for l in lines if "unloaded" in l["text"])
    assert [l["id"] for l in lines] == list(range(1, len(lines) + 1)) and len(lines) == 3, [(l["id"], l["text"]) for l in lines]
    seen3 = []
    def fp4(url, json=None, **k):
        if url.endswith("/chat"):
            seen3.append(json["messages"][0]["content"])
            return R(200, {"message": {"content": '{"answer":"It is in the log.","target":{"text_id": %d, "text":"unloaded gemma4","description":"log line","region":"center"}}' % want["id"]}})
        return R(200, {})
    screen.requests = types.SimpleNamespace(get=fget, post=fp4)
    screen.capture = lambda p, *a: (lg.save(p), True)[1]
    res = screen.look(cfg3, "where does it say unloaded gemma4?", [])
    assert "unloaded gemma4:latest" in seen3[0] and len(seen3) == 1, seen3     # the list of real text went to the model; one call only
    b = res["target"]["box"]
    x1, x2 = b[0] * 1800, b[2] * 1800
    assert x2 - x1 < 450 and x1 > 150, (x1, x2)                                  # narrowed to the words, not the whole 750px line
    assert b[1] * 700 > 150 and b[3] * 700 < 300, b
    print("ok model picks a real OCR line id")
print("ALL OK")
