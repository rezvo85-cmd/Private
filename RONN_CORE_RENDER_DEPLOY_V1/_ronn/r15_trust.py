"""RONN R15 trust, evidence and rollback journal."""
from __future__ import annotations
import json, sqlite3, time, uuid
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r15_trust.db"
DB.parent.mkdir(exist_ok=True)

def _db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS actions(
      id TEXT PRIMARY KEY, owner TEXT, action TEXT, target TEXT, risk TEXT,
      reversible INTEGER, before_state TEXT, after_state TEXT, evidence TEXT,
      status TEXT, created_at INTEGER, updated_at INTEGER)""")
    c.commit(); return c

def checkpoint(owner,action,target,before=None,after=None,risk="low",reversible=True,evidence=None):
    aid="act_"+uuid.uuid4().hex[:18]; now=int(time.time())
    pack=lambda x: json.dumps(x,ensure_ascii=False)[:120000] if x is not None else ""
    with _db() as c:
        c.execute("""INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (aid,str(owner)[:120],str(action)[:120],str(target)[:300],str(risk)[:20],
           1 if reversible else 0,pack(before),pack(after),pack(evidence),
           "completed",now,now))
        c.commit()
    return get(aid)

def add_evidence(action_id,evidence):
    with _db() as c:
        row=c.execute("SELECT evidence FROM actions WHERE id=?",(action_id,)).fetchone()
        if not row: return False
        try: current=json.loads(row["evidence"] or "[]")
        except Exception: current=[]
        if not isinstance(current,list): current=[current]
        current.append(evidence)
        c.execute("UPDATE actions SET evidence=?,updated_at=? WHERE id=?",
                  (json.dumps(current,ensure_ascii=False)[:120000],int(time.time()),action_id))
        c.commit()
    return True

def get(action_id):
    with _db() as c:
        r=c.execute("SELECT * FROM actions WHERE id=?",(str(action_id),)).fetchone()
    if not r: return None
    d=dict(r)
    for k in ("before_state","after_state","evidence"):
        try:d[k]=json.loads(d[k]) if d[k] else None
        except Exception:pass
    d["reversible"]=bool(d.get("reversible"))
    return d

def recent(owner,limit=30):
    with _db() as c:
        rows=c.execute("SELECT * FROM actions WHERE owner=? ORDER BY created_at DESC LIMIT ?",
                       (str(owner),max(1,min(int(limit),100)))).fetchall()
    return [get(r["id"]) for r in rows]

def rollback_payload(action_id):
    d=get(action_id)
    if not d: return {"ok":False,"reason":"not_found"}
    if not d.get("reversible"): return {"ok":False,"reason":"not_reversible","action":d}
    return {"ok":True,"action":d,"restore":d.get("before_state")}

def mark_rolled_back(action_id,evidence=None):
    with _db() as c:
        c.execute("UPDATE actions SET status='rolled_back',evidence=?,updated_at=? WHERE id=?",
          (json.dumps(evidence,ensure_ascii=False)[:120000] if evidence is not None else "",int(time.time()),str(action_id)))
        c.commit()
    return get(action_id)

def stats(owner=None):
    with _db() as c:
        if owner:
            total=c.execute("SELECT COUNT(*) n FROM actions WHERE owner=?",(str(owner),)).fetchone()["n"]
            rb=c.execute("SELECT COUNT(*) n FROM actions WHERE owner=? AND status='rolled_back'",(str(owner),)).fetchone()["n"]
        else:
            total=c.execute("SELECT COUNT(*) n FROM actions").fetchone()["n"]
            rb=c.execute("SELECT COUNT(*) n FROM actions WHERE status='rolled_back'").fetchone()["n"]
    return {"actions":int(total),"rolled_back":int(rb)}
