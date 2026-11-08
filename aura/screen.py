"""Look at the screen with a local vision model, and say where something is (for the pointer overlay)."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

log = logging.getLogger("aura.screen")

VISION_HINTS = ("gemma3", "gemma4", "llava", "vl", "vision", "minicpm-v", "moondream", "bakllava", "pixtral", "granite3.2-vision")


def _run_shot(cmds: list[list[str]], path: Path) -> bool:
    for c in cmds:
        try:
            path.unlink(missing_ok=True)
            subprocess.run(c, capture_output=True, timeout=20)
            if path.exists() and path.stat().st_size > 1000:
                return True
        except Exception as e:
            log.warning("screenshot with %s failed: %s", c[0], e)
    return False


def capture(path: Path, screens: list[dict] | None = None, target: str = "") -> bool:
    """Screenshot of ONE monitor.

    With several monitors we take the whole desktop and cut out the target monitor ourselves, so the picture and the
    pointer overlay always refer to the same screen. If the desktop picture can't be mapped to the monitors reliably we
    fall back to Spectacle's "current monitor" mode.
    """
    spectacle = shutil.which("spectacle")
    if spectacle and screens and len(screens) > 1 and target:
        tgt = next((s for s in screens if s["name"] == target), None)
        if tgt and _run_shot([["spectacle", "-b", "-n", "-f", "-o", str(path)]], path):
            try:
                from PIL import Image
                im = Image.open(path)
                ux, uy = min(s["x"] for s in screens), min(s["y"] for s in screens)
                uw = max(s["x"] + s["w"] for s in screens) - ux
                uh = max(s["y"] + s["h"] for s in screens) - uy
                sx, sy = im.width / uw, im.height / uh
                if abs(sx - sy) / sx < 0.03:
                    box = (round((tgt["x"] - ux) * sx), round((tgt["y"] - uy) * sy),
                           round((tgt["x"] - ux + tgt["w"]) * sx), round((tgt["y"] - uy + tgt["h"]) * sy))
                    im.crop(box).save(path)
                    log.info("screenshot: cut monitor %s out of the desktop picture %s", target, box)
                    return True
                log.warning("desktop screenshot %sx%s doesn't match the monitor layout %sx%s; using current-monitor mode",
                            im.width, im.height, uw, uh)
            except Exception as e:
                log.warning("couldn't cut the monitor out: %s", e)
    cmds = []
    if spectacle:
        cmds += [["spectacle", "-b", "-n", "-m", "-o", str(path)], ["spectacle", "-b", "-n", "-f", "-o", str(path)]]
    if shutil.which("grim"):
        cmds.append(["grim", str(path)])
    return _run_shot(cmds, path)


def has_vision(cfg, name: str) -> bool | None:
    """Ask Ollama whether a model can read images (capabilities list). None = couldn't tell."""
    try:
        r = requests.post(f"{str(cfg['ollama_url']).rstrip('/')}/api/show", json={"model": name}, timeout=5)
        caps = r.json().get("capabilities")
        if isinstance(caps, list):
            return "vision" in caps
    except Exception:
        pass
    return None


def vision_model(cfg, installed: list[str]) -> str | None:
    """Setting first; else the chat model if it can see; else any installed model that can."""
    want = str(cfg["vision_model"] or "").strip()
    if want:
        return want
    chat = str(cfg["model"])
    ordered = [chat] + [n for n in installed if n != chat]
    for name in ordered:
        if has_vision(cfg, name):
            return name
    for name in ordered:                      # older Ollama without capabilities: guess from the name
        if any(h in name.lower() for h in VISION_HINTS):
            return name
    return None


def _shrink(path: Path, max_side: int = 1280) -> tuple[bytes, int, int]:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    k = min(1.0, max_side / max(w, h))
    if k < 1:
        im = im.resize((int(w * k), int(h * k)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue(), w, h


COLS, ROWS = 12, 8
FINE = 8

PROMPT = """You are looking at a screenshot of the user's desktop. A grid is drawn over it. Every cell has a label in its
top-left corner: a column letter and a row number, e.g. "C4". Columns run A-{lastcol} left to right, rows 1-{rows} top to bottom.
Task: {question}

Reply with ONLY a JSON object:
{{"answer": "<short plain-language answer or the next step for the user, 1-3 sentences>",
  "target": null or {{"label": "<what to point at: its colour, shape and text, 3-8 words>", "cells": ["C4", "D4"]}}}}
"cells" lists the grid cells that the target (for example one button) covers; use as few as possible, usually 1-4.
Look carefully: pick the element that really answers the task, not another place that merely shows the same word.
Use null for "target" when nothing specific on the screen needs pointing at."""

REFINE = """This is a zoomed-in part of the user's screen with a finer grid (columns A-H, rows 1-8; labels in the top-left of each cell).
Find: {label}. (Context: {answer})
Reply with ONLY JSON: {{"found": true or false, "cells": ["B3", "C3"]}} listing the cells the element covers (as few as possible).
If that element is not visible here, answer {{"found": false, "cells": []}}."""


def _font(size: int):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/noto/NotoSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def cell_name(c: int, r: int) -> str:
    return f"{chr(65 + c)}{r + 1}"


def draw_grid(im, cols: int, rows: int, font_px: int):
    """Copy of the image with a thin labelled grid."""
    from PIL import ImageDraw
    im = im.convert("RGBA")
    over = __import__("PIL.Image", fromlist=["Image"]).new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    f = _font(font_px)
    w, h = im.size
    for c in range(cols + 1):
        x = round(c * w / cols)
        d.line([(x, 0), (x, h)], fill=(255, 40, 120, 150), width=1)
    for r in range(rows + 1):
        y = round(r * h / rows)
        d.line([(0, y), (w, y)], fill=(255, 40, 120, 150), width=1)
    for c in range(cols):
        for r in range(rows):
            x, y = round(c * w / cols) + 2, round(r * h / rows) + 2
            t = cell_name(c, r)
            tw = d.textlength(t, font=f)
            d.rectangle([x, y, x + tw + 6, y + font_px + 4], fill=(0, 0, 0, 190))
            d.text((x + 3, y + 1), t, fill=(255, 240, 80, 255), font=f)
    return __import__("PIL.Image", fromlist=["Image"]).alpha_composite(im, over).convert("RGB")


def cells_to_box(cells, cols: int, rows: int) -> list[float] | None:
    """["C4","D4"] -> [x1,y1,x2,y2] as fractions of the image; None if nothing valid."""
    cs, rs = [], []
    for name in cells or []:
        m = re.fullmatch(r"\s*([A-Za-z])\s*(\d{1,2})\s*", str(name))
        if not m:
            continue
        c, r = ord(m.group(1).upper()) - 65, int(m.group(2)) - 1
        if 0 <= c < cols and 0 <= r < rows:
            cs.append(c)
            rs.append(r)
    if not cs:
        return None
    return [min(cs) / cols, min(rs) / rows, (max(cs) + 1) / cols, (max(rs) + 1) / rows]


def _json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def parse_reply(text: str) -> dict:
    """Pull the JSON out of whatever the model said; never raise."""
    m = re.search(r"\{.*\}", text, re.S)
    obj = None
    if m:
        try:
            obj = json.loads(m.group(0))
        except Exception:
            obj = None
    if not isinstance(obj, dict):
        return {"answer": text.strip(), "target": None}
    ans = str(obj.get("answer") or "").strip() or text.strip()
    tgt = obj.get("target")
    box = None
    if isinstance(tgt, dict):
        try:
            b = [float(v) for v in tgt.get("box", [])][:4]
            if len(b) == 4:
                if max(b) > 1.5:                       # model answered in 0..1000 or pixels: normalise by the largest
                    scale = 1000.0 if max(b) <= 1000 else max(b)
                    b = [v / scale for v in b]
                x1, y1, x2, y2 = (min(max(v, 0.0), 1.0) for v in b)
                if x2 > x1 and y2 > y1:
                    box = {"label": str(tgt.get("label") or "").strip(), "box": [x1, y1, x2, y2]}
        except Exception:
            box = None
    return {"answer": ans, "target": box}


def _base(cfg) -> str:
    return str(cfg["ollama_url"]).rstrip("/")


def free_memory_for(cfg, keep: str) -> list[str]:
    """Unload every other model Ollama has in memory so the vision model fits on the GPU."""
    gone = []
    try:
        running = requests.get(f"{_base(cfg)}/api/ps", timeout=3).json().get("models", [])
        for m in running:
            name = m.get("name") or m.get("model")
            if name and name != keep:
                requests.post(f"{_base(cfg)}/api/generate", json={"model": name, "keep_alive": 0}, timeout=20)
                gone.append(name)
    except Exception as e:
        log.warning("couldn't unload other models: %s", e)
    return gone


def _jpeg(im, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _ask(cfg, model: str, prompt: str, jpg: bytes, num_ctx: int) -> tuple[str | None, str | None]:
    payload = {"model": model, "stream": False, "keep_alive": cfg["keep_alive"],
               "options": {"num_ctx": num_ctx, "temperature": 0.1},
               "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(jpg).decode()]}]}
    try:
        r = requests.post(f"{_base(cfg)}/api/chat", json=payload, timeout=(5, 240))
        if r.status_code != 200:
            return None, r.text[:300]
        return r.json().get("message", {}).get("content", ""), None
    except Exception as e:
        return None, str(e)


_OOM = re.compile(r"memory|alloc|cuda|oom|buffer", re.I)


# ------------------------------------------------------------------ text-anchored pointing (OCR)
TEXT_PROMPT = """You are looking at a screenshot of the user's desktop.
Task: {question}

Reply with ONLY a JSON object:
{{"answer": "<short plain-language answer or the next step for the user, 1-3 sentences>",
  "target": null or {{"text_id": <id of the line from the OCR list below that holds the words to point at, or null>,
                      "text": "<the exact words written ON the element to click or look at, copied character for character; \"\" if it has no text, e.g. an icon>",
                      "description": "<what it looks like and where: colour, shape, which window/panel, which part of the screen>",
                      "region": "<where on the screen: one of top-left, top, top-right, left, center, right, bottom-left, bottom, bottom-right>"}}}}
{ocr}Pick the element that really answers the task. If the same word appears in several places (for example in a terminal and on a button),
describe the right one so it can be told apart. Use null for "target" when nothing specific needs pointing at."""

PICK = """The screenshot has numbered boxes drawn on it. Which numbered box is: {description}?
(The text on it reads "{text}"; the user wants: {task})
Reply with ONLY JSON: {{"id": <number>}} using the number written next to the box."""


def _norm(t: str) -> str:
    return re.sub(r"[^\w ]+", "", t.lower()).strip()


def ocr_words(im) -> list[dict]:
    """Words with pixel boxes via the tesseract CLI (dark and light text: runs on the picture and its inverse)."""
    if not shutil.which("tesseract"):
        return []
    from PIL import ImageOps
    from concurrent.futures import ThreadPoolExecutor
    rgb = im.convert("RGB")
    r_, g_, b_ = rgb.split()
    # White text on a coloured button is only readable in some colour channels, so try several views of the picture.
    views = [("n", rgb.convert("L")), ("i", ImageOps.invert(rgb.convert("L"))), ("r", r_), ("g", g_), ("b", b_)]
    out: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="aura-ocr-") as d:
        def run(item):
            tag, img = item
            f = Path(d) / f"{tag}.png"
            img.save(f)
            try:
                r = subprocess.run(["tesseract", str(f), "stdout", "--psm", "11", "tsv"], capture_output=True,
                                   text=True, timeout=60)
            except Exception as e:
                log.warning("tesseract failed: %s", e)
                return []
            res = []
            for ln in r.stdout.splitlines()[1:]:
                c = ln.split("\t")
                if len(c) < 12 or c[0] != "5":
                    continue
                try:
                    conf, x, y, w, h = float(c[10]), int(c[6]), int(c[7]), int(c[8]), int(c[9])
                except ValueError:
                    continue
                text = c[11].strip()
                if not text or conf < 35 or w < 3 or h < 6:
                    continue
                res.append({"text": text, "box": [x, y, x + w, y + h], "line": (tag, c[2], c[3], c[4]), "conf": conf})
            return res
        with ThreadPoolExecutor(max_workers=5) as ex:
            for part in ex.map(run, views):
                out.extend(part)
    # the same word often appears in both passes: keep the one with higher confidence
    out.sort(key=lambda w: -w["conf"])
    kept: list[dict] = []
    for w in out:
        bx = w["box"]
        dup = False
        for k in kept:
            kb = k["box"]
            ix = max(0, min(bx[2], kb[2]) - max(bx[0], kb[0]))
            iy = max(0, min(bx[3], kb[3]) - max(bx[1], kb[1]))
            inter = ix * iy
            if inter > 0.5 * min((bx[2] - bx[0]) * (bx[3] - bx[1]), (kb[2] - kb[0]) * (kb[3] - kb[1])):
                dup = True
                break
        if not dup:
            kept.append(w)
    return kept


def _geo_lines(words: list[dict]) -> list[list[dict]]:
    """Group words into text lines by position (tesseract's own line ids fragment sparse screen text)."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w["box"][0]):
        b = w["box"]
        h = b[3] - b[1]
        cy = (b[1] + b[3]) / 2
        best = None
        for ln in lines:
            lb = ln[-1]["box"]
            lh = lb[3] - lb[1]
            if abs((lb[1] + lb[3]) / 2 - cy) < 0.5 * max(h, lh) and -0.3 * h <= b[0] - lb[2] <= 1.8 * max(h, lh):
                best = ln
                break
        if best is not None:
            best.append(w)
        else:
            lines.append([w])
    return lines


def ocr_lines(words: list[dict], limit: int = 140) -> list[dict]:
    """Words grouped into lines of text: [{"id","text","box","words"}] in reading order (what the model may point at)."""
    lines = []
    for ws in _geo_lines(words):
        text = " ".join(w["text"] for w in ws).strip()
        if len(re.sub(r"\W", "", text)) < 2:
            continue
        bs = [w["box"] for w in ws]
        lines.append({"text": text[:90], "words": ws, "box": [min(b[0] for b in bs), min(b[1] for b in bs),
                                                               max(b[2] for b in bs), max(b[3] for b in bs)]})
    # the same line is read in several colour channels: keep one per place
    lines.sort(key=lambda l: (l["box"][1] // 12, l["box"][0]))
    kept: list[dict] = []
    for l in lines:
        if not any(_iou(l["box"], k["box"]) > 0.5 for k in kept):
            kept.append(l)
    kept = kept[:limit]
    for i, l in enumerate(kept, 1):
        l["id"] = i
    return kept


def find_text(words: list[dict], target: str) -> list[dict]:
    """Places where the words of `target` appear next to each other on one line. [{"text","box"}...]"""
    import difflib
    toks = [t for t in _norm(target).split() if t]
    if not toks:
        return []
    hits = []
    for ws in _geo_lines(words):
        ws = sorted(ws, key=lambda w: w["box"][0])
        norm = [_norm(w["text"]) for w in ws]
        for i in range(len(ws) - len(toks) + 1):
            seg = norm[i:i + len(toks)]
            if all(a == b or (len(b) > 3 and (a.startswith(b) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)) for a, b in zip(seg, toks)):
                bs = [w["box"] for w in ws[i:i + len(toks)]]
                hits.append({"text": " ".join(w["text"] for w in ws[i:i + len(toks)]),
                             "box": [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]})
    return hits


_REGION = {"left": (0, 0.5), "right": (1, 0.5), "top": (0.5, 0), "bottom": (0.5, 1), "center": (0.5, 0.5), "middle": (0.5, 0.5)}


def region_center(region: str) -> tuple[float, float] | None:
    r = (region or "").lower()
    x = y = None
    for word, (px, py) in _REGION.items():
        if word in r:
            if word in ("left", "right"):
                x = px
            elif word in ("top", "bottom"):
                y = py
            else:
                x, y = (x if x is not None else px), (y if y is not None else py)
    if x is None and y is None:
        return None
    return (0.5 if x is None else x, 0.5 if y is None else y)


def _pick_hit(cfg, model, ctx, view, hits, tgt, question, W, H):
    """Several places show that text: number them and let the model choose; fall back to the stated region."""
    from PIL import ImageDraw
    hits = hits[:9]
    k = view.width / W
    im = view.copy()
    d = ImageDraw.Draw(im)
    f = _font(max(18, view.width // 45))
    for n, h in enumerate(hits, 1):
        b = [v * k for v in h["box"]]
        d.rectangle([b[0] - 4, b[1] - 4, b[2] + 4, b[3] + 4], outline=(255, 30, 120), width=3)
        label = str(n)
        tw = d.textlength(label, font=f)
        d.rectangle([b[0] - 4, b[1] - 4 - f.size - 6, b[0] - 4 + tw + 10, b[1] - 4], fill=(255, 30, 120))
        d.text((b[0] + 1, b[1] - 4 - f.size - 3), label, fill=(255, 255, 255), font=f)
    text, err = _ask(cfg, model, PICK.format(description=tgt.get("description") or tgt.get("text"), text=tgt.get("text"),
                                             task=question), _jpeg(im), ctx)
    obj = _json(text or "") if not err else None
    try:
        n = int(obj.get("id")) if obj else 0
    except (TypeError, ValueError):
        n = 0
    if 1 <= n <= len(hits):
        log.info("picked box %d of %d", n, len(hits))
        return hits[n - 1]
    rc = region_center(str(tgt.get("region") or ""))
    if rc:
        cx, cy = rc
        best = min(hits, key=lambda h: (((h["box"][0] + h["box"][2]) / 2 / W - cx) ** 2 + ((h["box"][1] + h["box"][3]) / 2 / H - cy) ** 2))
        log.info("model gave no valid box number; using the one nearest the %s", tgt.get("region"))
        return best
    return hits[0]


# ------------------------------------------------------------------ icons and shapes: numbered candidate boxes
SOM_PROMPT = """The screenshot has numbered boxes drawn on it (small coloured tags with a number at the top-left of each box).
The user wants: {question}
The element to point at is: {description}.
Which numbered box is exactly that element? Reply with ONLY JSON: {{"id": <number>}}, or {{"id": 0}} if none of the boxes is it."""


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _have_cv2() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def ui_boxes(im, max_boxes: int = 60) -> list[list[int]]:
    """Likely clickable things (buttons, icons, controls) as pixel boxes [x1,y1,x2,y2]. Needs OpenCV."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    rgb = np.array(im.convert("RGB"))
    H, W = rgb.shape[:2]
    unit = max(1.0, H / 1080.0)
    lo, hi = int(14 * unit), 0.30 * W
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cands: list[list[int]] = []

    def add(x, y, w, h):
        if w < lo or h < lo or w > hi or h > hi or w * h > 0.06 * W * H or max(w, h) / max(1, min(w, h)) > 9:
            return
        cands.append([int(x), int(y), int(x + w), int(y + h)])

    # 1) outlines: edges, thickened so an icon's strokes join into one blob
    edges = cv2.Canny(gray, 40, 120)
    for it, k in ((1, 3), (2, 3)):
        blob = cv2.dilate(edges, np.ones((k, k), np.uint8), iterations=it * max(1, int(unit)))
        cs, _ = cv2.findContours(blob, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            add(*cv2.boundingRect(c))
    # 2) flat, saturated areas: coloured buttons, badges, toggles
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = ((hsv[..., 1] > 80) & (hsv[..., 2] > 70)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area > 0.35 * w * h:
            add(x, y, w, h)
    # drop near-duplicates, then containers that merely hold many other candidates
    cands.sort(key=lambda b: -((b[2] - b[0]) * (b[3] - b[1])))
    kept: list[list[int]] = []
    for b in cands:
        if all(_iou(b, k) < 0.6 for k in kept):
            kept.append(b)
    def inside(a, b):
        return a[0] >= b[0] - 2 and a[1] >= b[1] - 2 and a[2] <= b[2] + 2 and a[3] <= b[3] + 2
    kept = [b for b in kept if sum(1 for o in kept if o is not b and inside(o, b)) < 4]
    kept = kept[:max_boxes]
    kept.sort(key=lambda b: (b[1] // int(60 * unit), b[0]))      # reading order
    return kept


def draw_marks(view, boxes, scale: float):
    """Numbered boxes on a copy of the picture. Box i is labelled i+1."""
    from PIL import ImageDraw
    im = view.copy()
    d = ImageDraw.Draw(im)
    f = _font(max(15, view.width // 80))
    palette = [(255, 40, 100), (30, 140, 255), (20, 190, 90), (255, 150, 0), (170, 60, 255)]
    for n, b in enumerate(boxes, 1):
        col = palette[n % len(palette)]
        x1, y1, x2, y2 = (v * scale for v in b)
        d.rectangle([x1, y1, x2, y2], outline=col, width=2)
        label = str(n)
        tw = d.textlength(label, font=f)
        ty = y1 - f.size - 4 if y1 > f.size + 6 else y1
        d.rectangle([x1, ty, x1 + tw + 8, ty + f.size + 4], fill=col)
        d.text((x1 + 4, ty + 1), label, fill=(255, 255, 255), font=f)
    return im


def _som_locate(cfg, model, ctx, full, view, question, tgt, W, H) -> dict | None:
    """Pick the right element among numbered candidate boxes. None when it can't (no OpenCV / nothing chosen)."""
    boxes = ui_boxes(full)
    if len(boxes) < 1:
        return None
    k = view.width / W
    desc = str(tgt.get("description") or tgt.get("text") or "the element").strip()
    text, err = _ask(cfg, model, SOM_PROMPT.format(question=question, description=desc),
                     _jpeg(draw_marks(view, boxes, k)), ctx)
    obj = _json(text or "") if not err else None
    try:
        n = int(obj.get("id")) if obj else 0
    except (TypeError, ValueError):
        n = 0
    log.info("icon pointing: %d candidate boxes, model chose %s for %r", len(boxes), n or "none", desc)
    if not (1 <= n <= len(boxes)):
        return None
    b = boxes[n - 1]
    pad = max(6, (b[3] - b[1]) * 0.15)
    return {"label": desc[:40], "box": [max(0, b[0] - pad) / W, max(0, b[1] - pad) / H,
                                         min(W, b[2] + pad) / W, min(H, b[3] + pad) / H]}


def _line_box(lines: list[dict], tgt: dict, W: int, H: int) -> dict | None:
    """The model named an OCR line: use its exact position (narrowed to the quoted words when they are inside it)."""
    try:
        i = int(tgt.get("text_id"))
    except (TypeError, ValueError):
        return None
    line = next((l for l in lines if l["id"] == i), None)
    if not line:
        return None
    box = line["box"]
    quoted = str(tgt.get("text") or "").strip()
    if quoted:
        hits = find_text(line["words"], quoted)
        if len(hits) >= 1:
            box = hits[0]["box"]
    log.info("model chose OCR line %d: %r", i, line["text"][:60])
    padx, pady = max(8, (box[3] - box[1]) * 0.7), max(6, (box[3] - box[1]) * 0.5)
    return {"label": str(tgt.get("description") or line["text"])[:40],
            "box": [max(0, box[0] - padx) / W, max(0, box[1] - pady) / H, min(W, box[2] + padx) / W, min(H, box[3] + pady) / H]}


def _text_locate_box(cfg, model, ctx, full, view, question, tgt, W, H, words=None):
    """Text on the element: OCR gives the exact position. Returns {"label","box"} or None."""
    if not shutil.which("tesseract"):
        log.warning("tesseract is not installed: text pointing is less accurate (sudo pacman -S tesseract tesseract-data-eng)")
        return None
    t = str(tgt.get("text") or "").strip()
    if not t:
        return None
    if words is None:
        words = ocr_words(full)
    hits = find_text(words, t)
    log.info("text %r: %d OCR words, %d matches", t, len(words), len(hits))
    if not hits:
        return None
    hit = hits[0] if len(hits) == 1 else _pick_hit(cfg, model, ctx, view, hits, tgt, question, W, H)
    b = hit["box"]
    padx, pady = max(10, (b[3] - b[1]) * 0.9), max(8, (b[3] - b[1]) * 0.6)
    return {"label": str(tgt.get("description") or t)[:40],
            "box": [max(0, b[0] - padx) / W, max(0, b[1] - pady) / H, min(W, b[2] + padx) / W, min(H, b[3] + pady) / H]}


def _grid_locate(cfg, model, ctx, full, view, question, W, H):
    """Last resort (no OCR match, no OpenCV): labelled grid + zoom. Returns (answer, target|None) or ("", error str)."""
    prompt = PROMPT.format(question=question, lastcol=chr(64 + COLS), rows=ROWS)
    text, err = _ask(cfg, model, prompt, _jpeg(draw_grid(view, COLS, ROWS, max(14, view.width // 60))), ctx)
    if err:
        return None, err
    obj = _json(text) or {}
    answer = str(obj.get("answer") or "").strip() or (text or "").strip()
    tgt = obj.get("target")
    if not isinstance(tgt, dict):
        return answer, None
    label = str(tgt.get("label") or "").strip()
    box = cells_to_box(tgt.get("cells"), COLS, ROWS)
    if box is None:
        return answer, None
    try:
        cw, ch = (box[2] - box[0]), (box[3] - box[1])
        mx, my = max(cw * 0.6, 1 / COLS), max(ch * 0.6, 1 / ROWS)
        rx1, ry1, rx2, ry2 = max(0.0, box[0] - mx), max(0.0, box[1] - my), min(1.0, box[2] + mx), min(1.0, box[3] + my)
        crop = full.crop((round(rx1 * W), round(ry1 * H), round(rx2 * W), round(ry2 * H)))
        sc = min(1000 / max(crop.size), 3.0)
        crop = crop.resize((max(64, int(crop.width * sc)), max(64, int(crop.height * sc))))
        t2, e2 = _ask(cfg, model, REFINE.format(label=label or "the target", answer=answer),
                      _jpeg(draw_grid(crop, FINE, FINE, max(14, crop.width // 28))), ctx)
        o2 = _json(t2 or "") if not e2 else None
        b2 = cells_to_box(o2.get("cells"), FINE, FINE) if o2 and o2.get("found") is not False else None
        if b2:
            bw, bh = rx2 - rx1, ry2 - ry1
            box = [rx1 + b2[0] * bw, ry1 + b2[1] * bh, rx1 + b2[2] * bw, ry1 + b2[3] * bh]
    except Exception:
        log.exception("refine pass failed")
    return answer, {"label": label, "box": box}


def _look_one(cfg, model, ctx, full, question) -> dict:
    """One monitor: answer + where to point. Order of preference: text position (OCR) -> numbered boxes (icons) -> grid."""
    W, H = full.size
    k = min(1.0, 1280 / max(W, H))
    view = full.resize((int(W * k), int(H * k))) if k < 1 else full
    words = ocr_words(full) if shutil.which("tesseract") else []
    lines = ocr_lines(words)
    ocr_block = ""
    if lines:
        ocr_block = ("Text found on this screen by OCR (it is exact; use it instead of guessing). Format  id: text\n"
                     + "\n".join(f"{l['id']}: {l['text']}" for l in lines) + "\n\n")
    prompt = TEXT_PROMPT.format(question=question, ocr=ocr_block)
    text, err = _ask(cfg, model, prompt, _jpeg(view), ctx)
    if err and _OOM.search(err):
        free_memory_for(cfg, "")
        time.sleep(1.5)
        ctx = 3072
        text, err = _ask(cfg, model, prompt, _jpeg(view), ctx)
    if err:
        hint = " The GPU is full. Pick a smaller vision model in Settings (e.g. gemma3:4b or gemma3:12b)." if _OOM.search(err) else ""
        return {"error": f"Vision model {model} failed: {err}.{hint}"}
    obj = _json(text or "") or {}
    answer = str(obj.get("answer") or "").strip() or (text or "").strip()
    out = {"answer": answer, "target": None}
    tgt = obj.get("target")
    if not isinstance(tgt, dict):
        return out
    try:
        t = _line_box(lines, tgt, W, H)
        if t is None:
            t = _text_locate_box(cfg, model, ctx, full, view, question, tgt, W, H, words)
        if t is None:
            t = _som_locate(cfg, model, ctx, full, view, question, tgt, W, H)
        if t is None and not _have_cv2():                # no OpenCV at all: old grid method
            a2, t = _grid_locate(cfg, model, ctx, full, view, question, W, H)
        out["target"] = t
    except Exception:
        log.exception("pointing failed")
    return out


def save_debug(name: str, img, target: dict | None) -> str | None:
    """Keep the last screenshot of each monitor and the same picture with the chosen box, for troubleshooting."""
    try:
        from PIL import ImageDraw
        from .config import DATA_DIR
        d = DATA_DIR / "debug"
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]", "_", name or "screen")
        img.save(d / f"last_{safe}.png")
        ann = img.copy()
        if target:
            W, H = ann.size
            b = target["box"]
            ImageDraw.Draw(ann).rectangle([b[0] * W, b[1] * H, b[2] * W, b[3] * H], outline=(255, 0, 80), width=max(3, W // 400))
        ann.save(d / f"last_{safe}_result.png")
        return str(d / f"last_{safe}_result.png")
    except Exception as e:
        log.warning("couldn't save debug images: %s", e)
        return None


def grab_screens(screens: list[dict] | None, names: list[str]) -> list[tuple[str, object]]:
    """[(monitor name, PIL image)] for the wanted monitors, from one desktop screenshot when possible."""
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix="aura-shot-") as d:
        path = Path(d) / "screen.png"
        multi = bool(screens) and len(screens) > 1 and shutil.which("spectacle")
        if multi and _run_shot([["spectacle", "-b", "-n", "-f", "-o", str(path)]], path):
            try:
                im = Image.open(path).convert("RGB")
                ux, uy = min(s["x"] for s in screens), min(s["y"] for s in screens)
                uw = max(s["x"] + s["w"] for s in screens) - ux
                uh = max(s["y"] + s["h"] for s in screens) - uy
                sx, sy = im.width / uw, im.height / uh
                if abs(sx - sy) / sx < 0.03:
                    out = []
                    for s in screens:
                        if s["name"] in names:
                            out.append((s["name"], im.crop((round((s["x"] - ux) * sx), round((s["y"] - uy) * sy),
                                                           round((s["x"] - ux + s["w"]) * sx), round((s["y"] - uy + s["h"]) * sy)))))
                    if out:
                        return out
                log.warning("desktop screenshot %sx%s doesn't match the monitor layout %sx%s", im.width, im.height, uw, uh)
            except Exception as e:
                log.warning("couldn't cut the monitors out: %s", e)
        one = names[0] if names else ""
        if capture(path, screens, one):
            return [(one, Image.open(path).convert("RGB"))]
    return []


def look(cfg, question: str, installed: list[str], screens: list[dict] | None = None, target: str = "",
         all_screens: bool = False) -> dict:
    """Returns {"answer", "target": {"label","box"}|None, "screen": name of the monitor the target is on, "error"}.

    With all_screens every monitor is looked at in turn and the answers are combined (the highlight goes to the first
    monitor that has a target, the one under the mouse first).
    """
    model = vision_model(cfg, installed)
    if not model:
        return {"error": "No vision model found. Your chat model can't read images. Set vision_model in Settings to one "
                         "that can (ollama show <model> lists \"vision\" under Capabilities), or `ollama pull gemma3:12b`."}
    names = [s["name"] for s in screens] if (all_screens and screens) else [target]
    if all_screens and target in names:
        names = [target] + [n for n in names if n != target]
    shots = grab_screens(screens, names)
    if not shots:
        return {"error": "Couldn't take a screenshot (needs `spectacle` on KDE, or `grim`)."}
    shots.sort(key=lambda t: names.index(t[0]) if t[0] in names else 99)
    same = model == str(cfg["model"])
    ctx = int(cfg["num_ctx"]) if same else 4096
    if not same:
        gone = free_memory_for(cfg, model)
        if gone:
            log.info("unloaded %s to make room for %s", ", ".join(gone), model)
    results = []
    for name, img in shots:
        r = _look_one(cfg, model, ctx, img, question if len(shots) == 1 else
                      f"{question} (This is monitor {name} of {len(shots)}; only describe what is on this monitor.)")
        if r.get("error"):
            return r
        r["screen"], r["size"] = name, img.size
        r["debug"] = save_debug(name, img, r.get("target"))
        log.info("debug images: %s", r["debug"])
        results.append(r)
    if len(results) == 1:
        results[0]["model"] = model
        return results[0]
    answer = " ".join(f"On monitor {r['screen']}: {r['answer']}" for r in results)
    hit = next((r for r in results if r.get("target")), None)
    return {"answer": answer, "target": hit["target"] if hit else None, "screen": hit["screen"] if hit else target,
            "model": model, "size": results[0]["size"]}
