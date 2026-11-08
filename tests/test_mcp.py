import sys, tempfile, pathlib
sys.path.insert(0, ".")
from aura.config import Config
from aura.mcp_client import MCPManager
from aura.tools import Registry
srv = sys.argv[1] if len(sys.argv) > 1 else None
if not srv:
    print("skip (pass a server script)"); sys.exit(0)
cfg = Config(pathlib.Path(tempfile.mkdtemp()) / "c.json")
cfg.set("mcp_servers", {"demo": {"command": sys.executable, "args": [srv]}, "bad": {"command": "/nonexistent"}})
reg = Registry(); m = MCPManager(cfg, reg); m.start()
assert "mcp_demo_add" in reg.tools, (reg.tools.keys(), m.status)
t = reg.get("mcp_demo_add"); assert t.confirm and set(t.required) == {"a", "b"}, (t.required, t.params)
assert t.fn(a=2, b=3).strip() == "5", t.fn(a=2, b=3)
assert m.status["bad"].startswith("failed"), m.status
m.stop(); print("ok mcp", m.status); print("ALL OK")
