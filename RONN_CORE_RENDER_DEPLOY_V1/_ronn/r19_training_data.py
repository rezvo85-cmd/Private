"""RONN R19 high-quality training/distillation dataset builder.

This does not train a model by itself. It creates a consented, inspectable dataset
from positively rated RONN runs so a future training job has clean examples.
"""
from __future__ import annotations
import json, os, sqlite3, time, uuid
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r19_training.db"
DB.parent.mkdir(exist_ok=True)
MAX_PENDING_PER_OWNER=max(50,min(2000,int(os.getenv("RONN_TRAINING_MAX_PENDING_PER_OWNER","250") or "250")))
PENDING_TTL_SECONDS=max(86400,min(30*86400,int(os.getenv("RONN_TRAINING_PENDING_TTL_DAYS","7") or "7")*86400))
MAX_EXAMPLES_PER_OWNER=max(500,min(20000,int(os.getenv("RONN_TRAINING_MAX_EXAMPLES_PER_OWNER","5000") or "5000")))

def _db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS examples(
      id TEXT PRIMARY KEY,owner TEXT,profile TEXT,prompt TEXT,response TEXT,model TEXT,
      source TEXT,created_at INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending(
      request_id TEXT PRIMARY KEY,owner TEXT,profile TEXT,prompt TEXT,response TEXT,model TEXT,created_at INTEGER)""")
    c.commit();return c


def _prune_owner(c, owner: str, now: int | None=None):
    now=int(time.time()) if now is None else int(now)
    cutoff=now-PENDING_TTL_SECONDS
    c.execute("DELETE FROM pending WHERE owner=? AND created_at<?",(owner,cutoff))
    c.execute(
        """DELETE FROM pending WHERE owner=? AND request_id NOT IN (
             SELECT request_id FROM pending WHERE owner=? ORDER BY created_at DESC LIMIT ?
           )""",
        (owner,owner,MAX_PENDING_PER_OWNER),
    )
    c.execute(
        """DELETE FROM examples WHERE owner=? AND id NOT IN (
             SELECT id FROM examples WHERE owner=? ORDER BY created_at DESC LIMIT ?
           )""",
        (owner,owner,MAX_EXAMPLES_PER_OWNER),
    )

def add(owner,prompt,response,profile="general",model="",source="positive_feedback"):
    if not str(prompt).strip() or not str(response).strip():return None
    eid="ex_"+uuid.uuid4().hex[:16]
    owner=str(owner)[:120]
    now=int(time.time())
    with _db() as c:
        c.execute("INSERT INTO examples VALUES(?,?,?,?,?,?,?,?)",
          (eid,owner,str(profile)[:60],str(prompt)[:24000],str(response)[:40000],str(model)[:180],str(source)[:80],now))
        _prune_owner(c,owner,now);c.commit()
    return eid

def stage(request_id,owner,prompt,response,profile="general",model=""):
    if not request_id or not str(prompt).strip() or not str(response).strip():return False
    owner=str(owner)[:120]
    now=int(time.time())
    with _db() as c:
        c.execute("""INSERT INTO pending VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(request_id) DO UPDATE SET owner=excluded.owner,profile=excluded.profile,
          prompt=excluded.prompt,response=excluded.response,model=excluded.model,created_at=excluded.created_at""",
          (str(request_id),owner,str(profile)[:60],str(prompt)[:24000],str(response)[:40000],str(model)[:180],now))
        _prune_owner(c,owner,now)
        c.commit()
    return True

def promote(request_id):
    with _db() as c:
        r=c.execute("SELECT * FROM pending WHERE request_id=?",(str(request_id),)).fetchone()
        if not r:return None
        eid="ex_"+uuid.uuid4().hex[:16]
        now=int(time.time())
        c.execute("INSERT INTO examples VALUES(?,?,?,?,?,?,?,?)",
          (eid,r["owner"],r["profile"],r["prompt"],r["response"],r["model"],"positive_feedback",now))
        c.execute("DELETE FROM pending WHERE request_id=?",(str(request_id),))
        _prune_owner(c,str(r["owner"]),now)
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
    return {
        "examples":int(n),
        "pending_feedback":int(p),
        "training_active":False,
        "dataset_ready":bool(n),
        "max_pending_per_owner":MAX_PENDING_PER_OWNER,
        "pending_ttl_seconds":PENDING_TTL_SECONDS,
        "max_examples_per_owner":MAX_EXAMPLES_PER_OWNER,
    }
