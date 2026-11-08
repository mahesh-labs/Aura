"""SQLite storage: conversations, messages and an audit log of every tool action."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New chat',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,              -- user | assistant | tool
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,                 -- json, assistant rows only
    tool_name TEXT,                  -- tool rows only
    tool_args TEXT,                  -- json, tool rows only
    source TEXT NOT NULL DEFAULT 'text',   -- text | voice
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    conv_id INTEGER,
    tool TEXT NOT NULL,
    args TEXT,
    result TEXT,
    status TEXT NOT NULL,            -- ok | error | denied
    ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    conv_id INTEGER,
    kind TEXT NOT NULL,              -- voice | chat | tool | approval | error | system
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""

# columns added after the first release (applied to existing databases on startup)
MIGRATIONS = [
    ("messages", "elapsed_ms", "INTEGER NOT NULL DEFAULT 0"),
    ("conversations", "pinned", "INTEGER NOT NULL DEFAULT 0"),
]


def _row(cur: sqlite3.Cursor, r: tuple) -> dict:
    return {d[0]: r[i] for i, d in enumerate(cur.description)}


class DB:
    def __init__(self, path: Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.row_factory = _row
        self._c.execute("PRAGMA foreign_keys=ON")
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r["name"] for r in self._c.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:
                self._c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self._c.commit()

    def _q(self, sql: str, args: tuple = (), commit: bool = False):
        with self._lock:
            cur = self._c.execute(sql, args)
            rows = cur.fetchall()
            if commit:
                self._c.commit()
            return rows, cur.lastrowid

    # ---- conversations -------------------------------------------------
    def create_conversation(self, title: str = "New chat") -> int:
        now = time.time()
        _, rid = self._q("INSERT INTO conversations(title,created,updated) VALUES(?,?,?)",
                         (title, now, now), commit=True)
        return rid

    def list_conversations(self) -> list[dict]:
        rows, _ = self._q("SELECT id AS convId, title, updated, pinned FROM conversations "
                          "ORDER BY pinned DESC, updated DESC")
        return rows

    def set_pinned(self, cid: int, pinned: bool) -> None:
        self._q("UPDATE conversations SET pinned=? WHERE id=?", (1 if pinned else 0, cid), commit=True)

    def rename_conversation(self, cid: int, title: str) -> None:
        self._q("UPDATE conversations SET title=? WHERE id=?", (title, cid), commit=True)

    def touch_conversation(self, cid: int) -> None:
        self._q("UPDATE conversations SET updated=? WHERE id=?", (time.time(), cid), commit=True)

    def delete_conversation(self, cid: int) -> None:
        self._q("DELETE FROM conversations WHERE id=?", (cid,), commit=True)

    def latest_conversation(self) -> int | None:
        rows, _ = self._q("SELECT id FROM conversations ORDER BY updated DESC LIMIT 1")
        return rows[0]["id"] if rows else None

    def conversation_updated(self, cid: int) -> float | None:
        rows, _ = self._q("SELECT updated FROM conversations WHERE id=?", (cid,))
        return rows[0]["updated"] if rows else None

    def conversation_title(self, cid: int) -> str | None:
        rows, _ = self._q("SELECT title FROM conversations WHERE id=?", (cid,))
        return rows[0]["title"] if rows else None

    # ---- messages ------------------------------------------------------
    def add_message(self, cid: int, role: str, content: str = "", *, tool_calls=None,
                    tool_name: str | None = None, tool_args=None, source: str = "text") -> dict:
        ts = time.time()
        _, rid = self._q(
            "INSERT INTO messages(conv_id,role,content,tool_calls,tool_name,tool_args,source,ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (cid, role, content,
             json.dumps(tool_calls) if tool_calls else None,
             tool_name,
             json.dumps(tool_args) if tool_args is not None else None,
             source, ts), commit=True)
        self.touch_conversation(cid)
        return self.get_message(rid)

    def get_message(self, mid: int) -> dict:
        rows, _ = self._q("SELECT * FROM messages WHERE id=?", (mid,))
        return self._decode(rows[0])

    def update_message(self, mid: int, *, content: str | None = None, tool_calls=None,
                       elapsed_ms: int | None = None) -> None:
        if elapsed_ms is not None:
            self._q("UPDATE messages SET elapsed_ms=? WHERE id=?", (int(elapsed_ms), mid), commit=True)
        if content is not None:
            self._q("UPDATE messages SET content=? WHERE id=?", (content, mid), commit=True)
        if tool_calls is not None:
            self._q("UPDATE messages SET tool_calls=? WHERE id=?", (json.dumps(tool_calls), mid), commit=True)

    def get_messages(self, cid: int) -> list[dict]:
        rows, _ = self._q("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (cid,))
        return [self._decode(r) for r in rows]

    @staticmethod
    def _decode(r: dict) -> dict:
        r = dict(r)
        r["tool_calls"] = json.loads(r["tool_calls"]) if r.get("tool_calls") else None
        r["tool_args"] = json.loads(r["tool_args"]) if r.get("tool_args") else None
        return r

    # ---- audit log -----------------------------------------------------
    def log_action(self, conv_id, tool: str, args, result: str, status: str, ms: int) -> dict:
        _, rid = self._q(
            "INSERT INTO actions(ts,conv_id,tool,args,result,status,ms) VALUES(?,?,?,?,?,?,?)",
            (time.time(), conv_id, tool, json.dumps(args, ensure_ascii=False), result[:4000], status, ms),
            commit=True)
        rows, _ = self._q("SELECT * FROM actions WHERE id=?", (rid,))
        return rows[0]

    def list_actions(self, limit: int = 300) -> list[dict]:
        rows, _ = self._q("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,))
        return rows

    def clear_actions(self) -> None:
        self._q("DELETE FROM actions", commit=True)

    # ---- events (voice, chat, approvals, errors ... shown on the Activity page) --------------
    def log_event(self, kind: str, title: str, detail: str = "", conv_id: int | None = None) -> dict:
        _, rid = self._q("INSERT INTO events(ts,conv_id,kind,title,detail) VALUES(?,?,?,?,?)",
                         (time.time(), conv_id, kind, title[:200], (detail or "")[:4000]), commit=True)
        rows, _ = self._q("SELECT * FROM events WHERE id=?", (rid,))
        return rows[0]

    def list_events(self, limit: int = 500) -> list[dict]:
        rows, _ = self._q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return rows

    def clear_events(self) -> None:
        self._q("DELETE FROM events", commit=True)
