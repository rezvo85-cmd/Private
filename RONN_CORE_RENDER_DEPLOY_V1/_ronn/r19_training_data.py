"""RONN R19 high-quality training/distillation dataset builder.

This does not train a model by itself. It creates a consented, inspectable dataset
from positively rated RONN runs so a future training job has clean examples.
"""
from __future__ import annotations
import json, sqlite3, time, uuid
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r19_training.db"
DB.parent.mkdir(exist_ok=True)

def _db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS examples(
      id TEXT PRIMARY KEY,owner TEXT,profile TEXT,prompt TEXT,response TEXT,model TEXT,
      source TEXT,created_at INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending(
      request_id TEXT PRIMARY KEY,owner TEXT,profile TEXT,prompt TEXT,response TEXT,model TEXT,created_at INTEGER)""")
    c.commit();return c

def add(owner,prompt,response,profile="general",model="",source="positive_feedback"):
    if not str(prompt).strip() or not str(response).strip():return None
    eid="ex_"+uuid.uuid4().hex[:16]
    with _db() as c:
        c.execute("INSERT INTO examples VALUES(?,?,?,?,?,?,?,?)",
          (eid,str(owner)[:120],str(profile)[:60],str(prompt)[:24000],str(response)[:40000],str(model)[:180],str(source)[:80],int(time.time())));c.commit()
    return eid

def stage(request_id,owner,prompt,response,profile="general",model=""):
    if not request_id or not str(prompt).strip() or not str(response).strip():return False
    with _db() as c:
        c.execute("""INSERT INTO pending VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(request_id) DO UPDATE SET owner=excluded.owner,profile=excluded.profile,
          prompt=excluded.prompt,response=excluded.response,model=excluded.model,created_at=excluded.created_at""",
          (str(request_id),str(owner)[:120],str(profile)[:60],str(prompt)[:24000],str(response)[:40000],str(model)[:180],int(time.time())))
        c.commit()
    return True

def promote(request_id):
    with _db() as c:
        r=c.execute("SELECT * FROM pending WHERE request_id=?",(str(request_id),)).fetchone()
        if not r:return None
        eid="ex_"+uuid.uuid4().hex[:16]
        c.execute("INSERT INTO examples VALUES(?,?,?,?,?,?,?,?)",
          (eid,r["owner"],r["profile"],r["prompt"],r["response"],r["model"],"positive_feedback",int(time.time())))
        c.execute("DELETE FROM pending WHERE request_id=?",(str(request_id),))
        c.commit()
    return eid

def discard(request_id):
    with _db() as c:
        cur=c.execute("DELETE FROM pending WHERE request_id=?",(str(request_id),));c.commit()
    return cur.rowcount>0

def pending_example(request_id):
    with _db() as c:r=c.execute("SELECT * FROM pending WHERE request_id=?",(str(request_id),)).fetchone()
    return dict(r) if r else None

def export(owner,limit=5000):
    with _db() as c:rows=c.execute("SELECT * FROM examples WHERE owner=? ORDER BY created_at LIMIT ?",(str(owner),max(1,min(int(limit),5000)))).fetchall()
    lines=[]
    for r in rows:
        lines.append(json.dumps({"messages":[{"role":"user","content":r["prompt"]},{"role":"assistant","content":r["response"]}],
                                 "metadata":{"profile":r["profile"],"model":r["model"],"source":r["source"]}},ensure_ascii=False))
    return "\n".join(lines)

def stats(owner=None):
    with _db() as c:
        n=c.execute("SELECT COUNT(*) n FROM examples"+(" WHERE owner=?" if owner else ""),((str(owner),) if owner else ())).fetchone()["n"]
    with _db() as c:
        p=c.execute("SELECT COUNT(*) n FROM pending"+(" WHERE owner=?" if owner else ""),((str(owner),) if owner else ())).fetchone()["n"]
    return {"examples":int(n),"pending_feedback":int(p),"training_active":False,"dataset_ready":bool(n)}
