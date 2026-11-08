"""MCP (Model Context Protocol) client: tools from MCP servers show up as Aura tools.

Configure in ~/.config/aura/config.json:
  "mcp_servers": {"files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/Documents"]}}
Each tool is added as  mcp_<server>_<tool>  and asks for approval before it runs (change that under Settings -> tools).
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from contextlib import AsyncExitStack

from .tools import REGISTRY, Tool

log = logging.getLogger("aura.mcp")


def _safe(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)[:40]


class MCPManager:
    def __init__(self, cfg, registry=REGISTRY):
        self.cfg = cfg
        self.registry = registry
        self.status: dict[str, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict = {}
        self._added: list[str] = []

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        servers = self.cfg["mcp_servers"] or {}
        if not servers or (self._thread and self._thread.is_alive()):
            return
        try:
            import mcp  # noqa: F401
        except Exception:
            self.status["*"] = "the 'mcp' package is not installed (pip install mcp)"
            log.warning(self.status["*"])
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(servers, ready), daemon=True, name="mcp")
        self._thread.start()
        ready.wait(timeout=60)

    def stop(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        for n in self._added:
            self.registry.tools.pop(n, None)
        self._added.clear()

    def _run(self, servers: dict, ready: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def main():
            stack = AsyncExitStack()
            try:
                for name, spec in servers.items():
                    try:
                        await asyncio.wait_for(self._connect(stack, name, spec), timeout=45)
                    except Exception as e:
                        self.status[name] = f"failed: {e}"
                        log.warning("MCP server %s failed: %s", name, e)
            finally:
                ready.set()
            await asyncio.Event().wait()      # keep the sessions alive until the loop is stopped

        try:
            loop.run_until_complete(main())
        except (RuntimeError, asyncio.CancelledError):
            pass
        finally:
            ready.set()

    async def _connect(self, stack: AsyncExitStack, name: str, spec: dict) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=spec["command"], args=list(spec.get("args", [])),
                                       env=spec.get("env") or None)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session
        listed = await session.list_tools()
        n = 0
        for t in listed.tools:
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}
            if not isinstance(schema, dict) and hasattr(schema, "model_dump"):
                schema = schema.model_dump(by_alias=True)
            props = dict(schema.get("properties") or {})
            full = f"mcp_{_safe(name)}_{_safe(t.name)}"
            self.registry.add(Tool(
                name=full, description=f"[{name}] {t.description or t.name}", params=props,
                required=tuple(schema.get("required") or ()),
                fn=self._caller(name, t.name), confirm=True,
                describe=lambda a, _n=name, _t=t.name: f"{_n}: {_t}({', '.join(f'{k}={v!r}' for k, v in a.items())})"))
            self._added.append(full)
            n += 1
        self.status[name] = f"{n} tools"
        log.info("MCP server %s: %d tools", name, n)

    def _caller(self, server: str, tool: str):
        def call(**kwargs) -> str:
            loop, session = self._loop, self._sessions.get(server)
            if not loop or session is None:
                return f"Error: MCP server {server} is not connected."
            fut = asyncio.run_coroutine_threadsafe(session.call_tool(tool, kwargs), loop)
            try:
                res = fut.result(timeout=120)
            except Exception as e:
                return f"Error: {e}"
            parts = [getattr(c, "text", None) or f"[{getattr(c, 'type', 'content')}]" for c in res.content]
            text = "\n".join(parts).strip() or "OK"
            return ("Error: " if getattr(res, "isError", False) else "") + text[:6000]
        return call
