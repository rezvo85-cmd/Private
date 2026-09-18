import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "core_v1.sqlite3"
DB.parent.mkdir(parents=True, exist_ok=True)


def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects(
          owner TEXT NOT NULL, project_id TEXT NOT NULL, name TEXT NOT NULL,
          description TEXT DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY(owner, project_id)
        );
        CREATE TABLE IF NOT EXISTS conversations(
          owner TEXT NOT NULL, conversation_id TEXT NOT NULL, project_id TEXT DEFAULT 'default',
          title TEXT DEFAULT 'New chat', created REAL NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY(owner, conversation_id)
        );
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
          conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
          metadata_json TEXT DEFAULT '{}', created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_core_messages_conv ON messages(owner, conversation_id, id);
        CREATE TABLE IF NOT EXISTS settings(
          owner TEXT PRIMARY KEY, settings_json TEXT NOT NULL, updated REAL NOT NULL
        );
        """
    )
    return c


def _id(prefix):
    return prefix + "_" + uuid.uuid4().hex[:20]


def ensure_default_project(owner):
    now = time.time()
    with _db() as c:
        c.execute(
            "INSERT OR IGNORE INTO projects(owner,project_id,name,description,created,updated) VALUES(?,?,?,?,?,?)",
            (owner, "default", "Default", "", now, now),
        )
    return "default"


def list_projects(owner):
    ensure_default_project(owner)
    with _db() as c:
        rows = c.execute("SELECT * FROM projects WHERE owner=? ORDER BY updated DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def create_project(owner, name, description=""):
    name = (name or "Untitled project").strip()[:120]
    pid = _id("prj")
    now = time.time()
    with _db() as c:
        c.execute(
            "INSERT INTO projects(owner,project_id,name,description,created,updated) VALUES(?,?,?,?,?,?)",
            (owner, pid, name, (description or "")[:2000], now, now),
        )
    return get_project(owner, pid)


def get_project(owner, project_id):
    ensure_default_project(owner)
    with _db() as c:
        row = c.execute("SELECT * FROM projects WHERE owner=? AND project_id=?", (owner, project_id)).fetchone()
    return dict(row) if row else None


def update_project(owner, project_id, name=None, description=None):
    p = get_project(owner, project_id)
    if not p:
        return None
    fields, args = [], []
    if name is not None:
        fields.append("name=?"); args.append((name or "Untitled project").strip()[:120])
    if description is not None:
        fields.append("description=?"); args.append((description or "")[:2000])
    fields.append("updated=?"); args.append(time.time())
    args += [owner, project_id]
    with _db() as c:
        c.execute(f"UPDATE projects SET {','.join(fields)} WHERE owner=? AND project_id=?", args)
    return get_project(owner, project_id)


def delete_project(owner, project_id):
    if project_id == "default":
        return False
    with _db() as c:
        cur = c.execute("DELETE FROM projects WHERE owner=? AND project_id=?", (owner, project_id))
        c.execute("UPDATE conversations SET project_id='default' WHERE owner=? AND project_id=?", (owner, project_id))
    return cur.rowcount > 0


def create_conversation(owner, project_id="default", title="New chat"):
    ensure_default_project(owner)
    if not get_project(owner, project_id):
        project_id = "default"
    cid = _id("conv")
    now = time.time()
    with _db() as c:
        c.execute(
            "INSERT INTO conversations(owner,conversation_id,project_id,title,created,updated) VALUES(?,?,?,?,?,?)",
            (owner, cid, project_id, (title or "New chat")[:160], now, now),
        )
    return get_conversation(owner, cid, include_messages=False)


def ensure_conversation(owner, conversation_id=None, project_id="default", title="New chat"):
    if conversation_id:
        found = get_conversation(owner, conversation_id, include_messages=False)
        if found:
            return found
    return create_conversation(owner, project_id, title)


def list_conversations(owner, project_id=None, limit=100):
    with _db() as c:
        if project_id:
            rows = c.execute(
                "SELECT * FROM conversations WHERE owner=? AND project_id=? ORDER BY updated DESC LIMIT ?",
                (owner, project_id, int(limit)),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM conversations WHERE owner=? ORDER BY updated DESC LIMIT ?",
                (owner, int(limit)),
            ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(owner, conversation_id, include_messages=True):
    with _db() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE owner=? AND conversation_id=?", (owner, conversation_id)
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        if include_messages:
            msgs = c.execute(
                "SELECT id,role,content,metadata_json,created FROM messages WHERE owner=? AND conversation_id=? ORDER BY id ASC",
                (owner, conversation_id),
            ).fetchall()
            out["messages"] = []
            for m in msgs:
                d = dict(m)
                try:
                    d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
                except Exception:
                    d["metadata"] = {}; d.pop("metadata_json", None)
                out["messages"].append(d)
    return out


def add_message(owner, conversation_id, role, content, metadata=None):
    content = (content or "").strip()
    if not content:
        return None
    now = time.time()
    with _db() as c:
        cur = c.execute(
            "INSERT INTO messages(owner,conversation_id,role,content,metadata_json,created) VALUES(?,?,?,?,?,?)",
            (owner, conversation_id, role[:20], content[:100000], json.dumps(metadata or {}, ensure_ascii=False), now),
        )
        c.execute("UPDATE conversations SET updated=? WHERE owner=? AND conversation_id=?", (now, owner, conversation_id))
        if role == "user":
            row = c.execute("SELECT title FROM conversations WHERE owner=? AND conversation_id=?", (owner, conversation_id)).fetchone()
            if row and (row["title"] or "") == "New chat":
                title = " ".join(content.split())[:72] or "New chat"
                c.execute("UPDATE conversations SET title=? WHERE owner=? AND conversation_id=?", (title, owner, conversation_id))
        return int(cur.lastrowid)


def delete_conversation(owner, conversation_id):
    with _db() as c:
        c.execute("DELETE FROM messages WHERE owner=? AND conversation_id=?", (owner, conversation_id))
        cur = c.execute("DELETE FROM conversations WHERE owner=? AND conversation_id=?", (owner, conversation_id))
    return cur.rowcount > 0


DEFAULT_SETTINGS = {"response_style": "auto", "reasoning_mode": "auto", "agent_mode": True}


def get_settings(owner):
    with _db() as c:
        row = c.execute("SELECT settings_json FROM settings WHERE owner=?", (owner,)).fetchone()
    if not row:
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(row["settings_json"] or "{}")
    except Exception:
        data = {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in data.items() if k in DEFAULT_SETTINGS}}


def update_settings(owner, patch):
    current = get_settings(owner)
    allowed = set(DEFAULT_SETTINGS)
    for k, v in (patch or {}).items():
        if k in allowed:
            current[k] = v
    current["agent_mode"] = bool(current.get("agent_mode", True))
    if current.get("response_style") == "short":
        current["response_style"] = "concise"
    if current.get("response_style") not in {"auto", "concise", "balanced", "detailed"}:
        current["response_style"] = "auto"
    if current.get("reasoning_mode") not in {"auto", "fast", "deep", "apex"}:
        current["reasoning_mode"] = "auto"
    with _db() as c:
        c.execute(
            "INSERT INTO settings(owner,settings_json,updated) VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET settings_json=excluded.settings_json,updated=excluded.updated",
            (owner, json.dumps(current), time.time()),
        )
    return current


def stats(owner):
    ensure_default_project(owner)
    with _db() as c:
        p = c.execute("SELECT COUNT(*) n FROM projects WHERE owner=?", (owner,)).fetchone()["n"]
        conv = c.execute("SELECT COUNT(*) n FROM conversations WHERE owner=?", (owner,)).fetchone()["n"]
        msg = c.execute("SELECT COUNT(*) n FROM messages WHERE owner=?", (owner,)).fetchone()["n"]
    return {"projects": p, "conversations": conv, "messages": msg}


# R21 cloud-store delegation: Render/production uses Postgres when DATABASE_URL is bound.
# Local/offline runs keep the existing SQLite implementation.
if (os.getenv("DATABASE_URL") or "").strip():
    from core_store_pg import (
        ensure_default_project, list_projects, create_project, get_project, update_project,
        delete_project, create_conversation, ensure_conversation, list_conversations,
        get_conversation, add_message, delete_conversation, get_settings, update_settings,
        stats,
    )
