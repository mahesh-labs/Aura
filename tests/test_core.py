"""Core tests against a mock Ollama server (no Qt, no audio needed). Run: python -m pytest tests -q  or  python tests/test_core.py"""
import json, sys, threading, tempfile, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aura.config import Config
from aura.db import DB
from aura.agent import Agent, Sink, SentenceSplitter, speakable
from aura.tools import REGISTRY

SCRIPT = []   # list of lists of ndjson dicts; one entry per /api/chat call
SEEN = []     # request payloads


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen3-coder:30b"}, {"name": "x:1b"}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers["Content-Length"]); payload = json.loads(self.rfile.read(n))
        SEEN.append(payload)
        if self.path == "/api/chat":
            chunks = SCRIPT.pop(0)
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for c in chunks:
                self.wfile.write((json.dumps(c) + "\n").encode()); self.wfile.flush()
        else:
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}")


class Rec(Sink):
    def __init__(self): self.added, self.updated, self.sent, self.actions, self.errors, self.statuses = [], [], [], [], [], []
    def message_added(self, c, m): self.added.append(m)
    def message_updated(self, c, i, p): self.updated.append((i, p))
    def sentence(self, t): self.sent.append(t)
    def status(self, t): self.statuses.append(t)
    def action(self, r): self.actions.append(r)
    def error(self, t): self.errors.append(t)


def tok(t): return {"message": {"role": "assistant", "content": t}, "done": False}
def call(name, **args): return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}, "done": False}
DONE = {"message": {"role": "assistant", "content": ""}, "done": True}


def setup():
    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tempfile.mkdtemp()
    cfg = Config(Path(d) / "c.json"); cfg.set("ollama_url", f"http://127.0.0.1:{srv.server_port}")
    db = DB(Path(d) / "t.db")
    return srv, cfg, db, Agent(cfg, db), d


def test_text_and_tool_loop():
    srv, cfg, db, agent, d = setup()
    SCRIPT[:] = [[tok("Let me check. "), call("get_datetime"), DONE], [tok("It is "), tok("late."), DONE]]
    cid = db.create_conversation(); sink = Rec()
    agent.run_turn(cid, "what time is it", voice=False, cancel=threading.Event(), sink=sink, confirm=lambda n, d: True)
    roles = [m["role"] for m in db.get_messages(cid)]
    assert roles == ["user", "assistant", "tool", "assistant"], roles
    assert sink.actions and sink.actions[0]["tool"] == "get_datetime" and sink.actions[0]["status"] == "ok"
    # second request must contain the tool result and the assistant tool_calls
    second = SEEN[-1]["messages"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_name"] == "get_datetime"
    assert second[-2]["tool_calls"][0]["function"]["name"] == "get_datetime"
    assert db.get_messages(cid)[-1]["content"] == "It is late."
    assert db.list_conversations()[0]["title"] == "what time is it"
    assert any(t["function"]["name"] == "run_shell" for t in SEEN[0]["tools"])
    assert SEEN[0]["options"]["num_ctx"] == 32768
    print("ok text+tool loop")


def test_confirm_deny_and_allow():
    srv, cfg, db, agent, d = setup()
    marker = Path(d) / "made.txt"
    asked = []
    SCRIPT[:] = [[call("run_shell", command=f"touch {marker}"), DONE], [tok("Sorry, not done."), DONE]]
    cid = db.create_conversation(); sink = Rec()
    agent.run_turn(cid, "make a file", voice=False, cancel=threading.Event(), sink=sink,
                   confirm=lambda n, d: asked.append((n, d)) or False)
    assert asked and asked[0][0] == "run_shell" and "touch" in asked[0][1]
    assert not marker.exists() and sink.actions[0]["status"] == "denied"
    # now allow
    SCRIPT[:] = [[call("run_shell", command=f"touch {marker}"), DONE], [tok("Done."), DONE]]
    agent.run_turn(cid, "again", voice=False, cancel=threading.Event(), sink=Rec(), confirm=lambda n, d: True)
    assert marker.exists()
    print("ok confirmation")


def test_voice_sentences_and_override():
    srv, cfg, db, agent, d = setup()
    SCRIPT[:] = [[tok("Sure thing, boss. "), tok("Opening it **now** with "), tok("https://x.io/a link. Done"), DONE]]
    cid = db.create_conversation(); sink = Rec()
    agent.run_turn(cid, "hi", voice=True, cancel=threading.Event(), sink=sink, confirm=lambda n, d: True)
    assert sink.sent[0].startswith("Sure thing") and "**" not in " ".join(sink.sent) and "http" not in " ".join(sink.sent), sink.sent
    assert sink.sent[-1].endswith("Done"), sink.sent
    assert "spoken aloud" in SEEN[-1]["messages"][0]["content"]
    assert db.get_messages(cid)[0]["source"] == "voice"
    # ask override makes a safe tool ask
    cfg.set("ask_overrides", {"get_datetime": True})
    asked = []
    SCRIPT[:] = [[call("get_datetime"), DONE], [tok("ok"), DONE]]
    agent.run_turn(cid, "t", voice=False, cancel=threading.Event(), sink=Rec(), confirm=lambda n, d: asked.append(n) or True)
    assert asked == ["get_datetime"]
    cfg.set("disabled_tools", ["get_datetime"])
    SCRIPT[:] = [[call("get_datetime"), DONE], [tok("ok"), DONE]]
    s = Rec(); agent.run_turn(cid, "t", voice=False, cancel=threading.Event(), sink=s, confirm=lambda n, d: True)
    assert s.actions[-1]["status"] == "error"
    print("ok voice sentences, overrides")


def test_errors_and_cancel():
    srv, cfg, db, agent, d = setup()
    cfg.set("ollama_url", "http://127.0.0.1:9")   # nothing listening
    cid = db.create_conversation(); sink = Rec()
    agent.run_turn(cid, "hi", voice=False, cancel=threading.Event(), sink=sink, confirm=lambda n, d: True)
    assert sink.errors and "Ollama" in sink.errors[0]
    assert db.get_messages(cid)[-1]["content"].startswith("⚠️")
    print("ok error handling")


def test_splitter_and_speakable():
    sp = SentenceSplitter(); out = []
    for t in ["Hello the", "re. How are", " you? Fine", "!\n", "tail"]:
        out += sp.feed(t)
    out += sp.flush()
    assert out == ["Hello there. How are you?", "Fine!\ntail"], out   # short sentences merge (better TTS prosody)
    sp = SentenceSplitter(min_len=1); o2 = sp.feed("One. Two! Three") + sp.flush()
    assert o2 == ["One.", "Two!", "Three"], o2
    assert speakable("See [docs](http://a.b) and `code` # Head") == "See docs and code Head"
    print("ok splitter")


def test_tools_local():
    d = tempfile.mkdtemp()
    p = Path(d) / "hello world.txt"
    assert "Wrote" in REGISTRY.get("write_text_file").fn(str(p), "hi there")
    assert REGISTRY.get("read_text_file").fn(str(p)) == "hi there"
    assert "hello world.txt" in REGISTRY.get("search_files").fn("hello", d)
    assert "hello world.txt" in REGISTRY.get("list_directory").fn(d)
    r = REGISTRY.get("run_shell").fn("echo hi; echo err 1>&2", d)
    assert "exit 0" in r and "hi" in r and "err" in r
    assert "Error" in REGISTRY.get("set_volume").fn(50) or "Volume" in REGISTRY.get("set_volume").fn(50)   # wpctl may be missing here
    assert "CPU" in REGISTRY.get("system_info").fn()
    assert REGISTRY.get("open_app").fn("definitely-not-an-app-xyz").startswith("No installed")
    sch = REGISTRY.schemas(Config(Path(d) / "x.json"))
    assert all(s["function"]["parameters"]["type"] == "object" for s in sch) and len(sch) >= 20
    print("ok tools:", len(sch), "schemas")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ALL OK")
