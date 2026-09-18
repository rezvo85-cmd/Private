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
      source TEXT,created_at INTEGER)""");c.commit();return c

def add(owner,prompt,response,profile="general",model="",source="positive_feedback"):
    if not str(prompt).strip() or not str(response).strip():return None
    eid="ex_"+uuid.uuid4().hex[:16]
    with _db() as c:
        c.execute("INSERT INTO examples VALUES(?,?,?,?,?,?,?,?)",
          (eid,str(owner)[:120],str(profile)[:60],str(prompt)[:24000],str(response)[:40000],str(model)[:180],str(source)[:80],int(time.time())));c.commit()
    return eid

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
    return {"examples":int(n),"training_active":False,"dataset_ready":bool(n)}
