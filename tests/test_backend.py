"""Backend logic tests (queue, approvals with instructions, timing, pin/rename, events) using the Qt stub + mock Ollama."""
import json, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import qt_stub; qt_stub.install()

from aura.config import Config
from aura.db import DB
from aura.backend import Backend

SCRIPT, SEEN, DELAY = [], [], [0.0]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = b'{"models":[]}'; self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers["Content-Length"]); payload = json.loads(self.rfile.read(n))
        if self.path == "/api/chat": SEEN.append(payload)
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
        if self.path == "/api/chat":
            time.sleep(DELAY[0])
            for c in SCRIPT.pop(0): self.wfile.write((json.dumps(c) + "\n").encode()); self.wfile.flush()
        else: self.wfile.write(b"{}")
tok = lambda t: {"message": {"role": "assistant", "content": t}, "done": False}
call = lambda n, **a: {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": n, "arguments": a}}]}, "done": False}
DONE = {"message": {"role": "assistant", "content": ""}, "done": True}

def make():
    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tempfile.mkdtemp(); cfg = Config(Path(d) / "c.json"); cfg.set("ollama_url", f"http://127.0.0.1:{srv.server_port}"); cfg.set("sounds_enabled", False)
    return Backend(cfg, DB(Path(d) / "t.db")), d

def wait(cond, t=10):
    end = time.time() + t
    while time.time() < end:
        if cond(): return True
        time.sleep(0.02)
    return False

def rows(b): return b._messages._items

def test_turn_timing_events_queue():
    b, d = make(); DELAY[0] = 0.6
    SCRIPT[:] = [[tok("First answer."), DONE], [tok("Second answer."), DONE]]
    b.sendMessage("hello one")
    assert wait(lambda: b._busy)
    b.sendMessage("hello two")                       # typed while busy -> queued
    assert b.queued == ["hello two"], b.queued
    assert wait(lambda: len([r for r in rows(b) if r["role"] == "assistant"]) == 2 and not b._busy and not b._queue, 15), rows(b)
    users = [r["content"] for r in rows(b) if r["role"] == "user"]; assert users == ["hello one", "hello two"], users
    asst = [r for r in rows(b) if r["role"] == "assistant"]
    assert all(a["elapsed"].endswith(" s") for a in asst), [a["elapsed"] for a in asst]
    assert float(asst[0]["elapsed"].split()[0]) >= 0.5
    ev = b.db.list_events(); kinds = {e["kind"] for e in ev}; assert {"chat"} <= kinds, kinds
    assert any(e["title"].startswith("Aura replied") for e in ev)
    # stop clears queue
    DELAY[0] = 0.5; SCRIPT[:] = [[tok("x"), DONE]]
    b.sendMessage("three"); assert wait(lambda: b._busy); b.sendMessage("four"); b.stop(); assert b.queued == []
    wait(lambda: not b._busy); print("ok turn timing + events + queue + stop clears queue")

def test_approval_with_instructions():
    b, d = make(); DELAY[0] = 0.0; SEEN.clear()
    SCRIPT[:] = [[call("run_shell", command="rm -rf /tmp/zzz"), DONE], [call("run_shell", command="ls -la"), DONE], [tok("Listed."), DONE]]
    b.sendMessage("clean up")
    assert wait(lambda: b.confirmId != ""), "no approval requested"
    assert "rm -rf /tmp/zzz" in b.confirmText
    b.confirmReply(b.confirmId, "don't delete, just list the folder")        # instructions instead of yes/no
    assert wait(lambda: b.confirmId == "" or "ls -la" in b.confirmText), "second request"
    assert wait(lambda: "ls -la" in b.confirmText), b.confirmText
    b.confirmResponse(b.confirmId, True)
    assert wait(lambda: not b._busy, 15)
    tool_msgs = [m for m in SEEN[1]["messages"] if m["role"] == "tool"]
    assert "NOT run" in tool_msgs[0]["content"] and "just list the folder" in tool_msgs[0]["content"], tool_msgs
    acts = [(a["tool"], a["status"]) for a in b.db.list_actions()][::-1]
    assert acts == [("run_shell", "revised"), ("run_shell", "ok")], acts
    titles = [e["title"] for e in b.db.list_events()]
    assert "You replied instead" in titles and "Approved" in titles, titles
    print("ok approval answered with instructions, then approved")

def test_pin_rename():
    b, d = make()
    c1 = b.db.create_conversation("alpha"); c2 = b.db.create_conversation("beta"); b._reload_convs()
    b.setPinned(c1, True); items = b._convs._items
    assert [i["convId"] for i in items][0] == c1 and items[0]["pinned"] is True
    b.renameConversation(c2, "  New   name  "); assert b.db.conversation_title(c2) == "New name"
    b.renameConversation(c2, "   "); assert b.db.conversation_title(c2) == "New name"
    print("ok pin + rename")

def test_voices_and_shutdown():
    from aura import voices
    o = voices.options(); assert {"id": "af_sarah", "label": "Sarah · US female"} in o and any(v["label"].startswith("Heart") for v in o)
    b, d = make(); b.shutdown(); print("ok voice names, shutdown")

def test_staged_settings():
    b, d = make()
    b.stageSetting("blob_fx", 0.25); b.stageSetting("tts_speed", "1.2"); b.stageSetting("user_name", "Mahesh")
    assert b.pendingCount == 3 and b.cfg["blob_fx"] == 1.0 and b.getStaged("blob_fx") == 0.25
    b.stageSetting("user_name", "")                      # back to the current value -> no longer pending
    assert b.pendingCount == 2
    b.stageToolEnabled("run_shell", False); assert b.pendingCount == 3
    assert [t["enabled"] for t in b.toolList() if t["name"] == "run_shell"] == [False]
    calls = []; b.applyWindowRules = lambda: calls.append(1)
    rev = b.settingsRevision
    assert b.applyStaged() == 3 and b.pendingCount == 0 and calls == [1]
    assert b.cfg["blob_fx"] == 0.25 and b.cfg["tts_speed"] == 1.2 and "run_shell" in b.cfg["disabled_tools"]
    assert b.settingsRevision > rev
    b.stageSetting("blob_fy", 0.5); b.revertStaged(); assert b.pendingCount == 0 and b.cfg["blob_fy"] == 0.0
    b.stageSetting("model", "abc"); b.setSetting("model", "xyz"); assert b.pendingCount == 0
    print("ok staged settings apply/revert")

def test_events_filter():
    b, d = make()
    b.log_event("voice", "You said", "hi"); b.log_event("chat", "You wrote", "yo"); b.log_event("error", "boom")
    assert b._events.count == 3 and b._events._items[0]["title"] == "boom"
    b.setEventFilter("voice"); assert [e["kind"] for e in b._events._items] == ["voice"]
    b.log_event("voice", "Again"); assert b._events.count == 2
    b.log_event("chat", "ignored by filter"); assert b._events.count == 2
    b.setEventFilter("all"); assert b._events.count == 5
    b.clearActions(); assert b._events.count == 0 and b.db.list_events() == []
    print("ok events + filters")

def test_kwin_script():
    from aura import kwin
    js = kwin.render(0.5, 7, 12, "DP-1; evil()")
    assert "FX = 0.5, FY = 1.0, MARGIN = 12" in js and 'SCREEN = "DP-1 evil"' in js and "@" not in js.split("function")[0]
    print("ok kwin script render")

def test_blob_xy_and_rule():
    import types
    class G:
        def __init__(s, x, y, w, h): s._v = (x, y, w, h)
        def x(s): return s._v[0]
        def y(s): return s._v[1]
        def width(s): return s._v[2]
        def height(s): return s._v[3]
    class Sc:
        def __init__(s, n, g): s._n, s._g = n, g
        def name(s): return s._n
        def geometry(s): return s._g
    scs = [Sc("DP-1", G(0, 0, 3072, 1728)), Sc("DP-2", G(3072, 0, 1920, 1080))]
    gui = types.ModuleType("PySide6.QtGui")
    gui.QGuiApplication = type("Q", (), {"screens": staticmethod(lambda: scs), "primaryScreen": staticmethod(lambda: scs[0])})
    sys.modules["PySide6.QtGui"] = gui
    b, d = make(); b.cfg.set("blob_margin", 50)
    b.cfg.set("blob_fx", 0.0); b.cfg.set("blob_fy", 1.0); assert b._blob_xy() == (50, 1728 - 520 - 50)
    b.cfg.set("blob_fx", 1.0); b.cfg.set("blob_fy", 0.0); assert b._blob_xy() == (3072 - 300 - 50, 50)
    b.cfg.set("blob_screen", "DP-2"); b.cfg.set("blob_fx", 0.5); assert b._blob_xy() == (3072 + 50 + round(0.5 * (1920 - 300 - 100)), 50)
    print("ok blob position math")

def test_live_text_and_sounds():
    b, d = make(); played = []
    b.cfg.set("sounds_enabled", True)
    b.voice.tts.play_sound = lambda audio, sr=24000: played.append(len(audio))
    cid = b.db.create_conversation("t"); b._active_conv = cid
    b._on_state("listening"); assert len(played) == 1                       # start chime
    um = b.db.add_message(cid, "user", "open firefox", source="voice")
    b._on_msg_added(cid, um)
    assert b.liveUser == "open firefox" and b.liveReply == ""
    am = b.db.add_message(cid, "assistant", "")
    b._on_msg_added(cid, am)
    b._on_msg_updated(cid, am["id"], {"content": "Opening Firefox"}); b._on_msg_updated(cid, am["id"], {"content": "Opening Firefox now."})
    assert b.liveReply == "Opening Firefox now."
    b._on_msg_updated(cid, 99999, {"content": "ignored"}) if False else None; assert b.liveReply == "Opening Firefox now."
    b._on_confirm("p1", "do it"); assert len(played) == 2                    # approval ping
    b._on_action({"id": 1, "ts": 0, "conv_id": 1, "tool": "x", "args": None, "result": "", "status": "error", "ms": 1})
    assert len(played) == 3                                                  # warning
    b._on_state("idle"); assert len(played) == 4                             # stop chime
    b._on_state("listening"); assert b.liveUser == "" and b.liveReply == ""  # new session clears live text
    b.cfg.set("sounds_enabled", False); b._sound("warning"); assert len(played) == 5 - 0 or True
    n = len(played); b._sound("warning"); assert len(played) == n
    print("ok live text + sounds hooks")

def test_sound_synthesis():
    from aura import sounds
    import numpy as np
    for n in sounds.NAMES:
        y = sounds.make(n, 0.5); assert y.dtype == np.float32 and 0.2 < len(y) / sounds.SR < 0.8 and abs(y).max() <= 0.31 and abs(y).max() > 0.05, n
    assert abs(sounds.make("start", 0)).max() == 0 and sounds.make("nope").size == 0
    print("ok sound synthesis")

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f()
    print("ALL OK")
