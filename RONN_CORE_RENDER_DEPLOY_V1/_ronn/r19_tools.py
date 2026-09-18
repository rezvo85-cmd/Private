"""RONN R19 self-created safe tools.

Tools are restricted Python programs validated/executed by the R14 sandbox.
They cannot import modules, access files/network, spawn processes, or read secrets.
"""
from __future__ import annotations
import sqlite3, time, uuid
from pathlib import Path
from r14_sandbox import execute, SandboxError

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r19_tools.db"
DB.parent.mkdir(exist_ok=True)

def _db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS tools(
      id TEXT PRIMARY KEY,owner TEXT,name TEXT,description TEXT,source TEXT,
      enabled INTEGER,created_at INTEGER,updated_at INTEGER)""")
    c.commit();return c

def create(owner,name,description,source):
    # Validation is real: the source must execute safely before it can be kept.
    validation=execute(str(source or ""))
    tid="tool_"+uuid.uuid4().hex[:16];now=int(time.time())
    with _db() as c:
        c.execute("INSERT INTO tools VALUES(?,?,?,?,?,?,?,?)",
          (tid,str(owner)[:120],str(name)[:100],str(description)[:500],str(source)[:8000],1,now,now));c.commit()
    return {"tool":get(owner,tid),"validation":validation}

def get(owner,tid):
    with _db() as c:r=c.execute("SELECT * FROM tools WHERE owner=? AND id=?",(str(owner),str(tid))).fetchone()
    return dict(r) if r else None

def list_tools(owner):
    with _db() as c:rows=c.execute("SELECT id,name,description,enabled,created_at,updated_at FROM tools WHERE owner=? ORDER BY updated_at DESC",(str(owner),)).fetchall()
    return [dict(r) for r in rows]

def run(owner,tid):
    t=get(owner,tid)
    if not t or not t.get("enabled"):raise ValueError("Tool not found or disabled.")
    return execute(t["source"])

def remove(owner,tid):
    with _db() as c:cur=c.execute("DELETE FROM tools WHERE owner=? AND id=?",(str(owner),str(tid)));c.commit()
    return cur.rowcount>0

def status(owner=None):
    with _db() as c:
        n=c.execute("SELECT COUNT(*) n FROM tools"+(" WHERE owner=?" if owner else ""),((str(owner),) if owner else ())).fetchone()["n"]
    return {"safe_tools":int(n),"runtime":"R14 restricted Python"}
