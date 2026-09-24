"""RONN R15 trust, evidence and rollback journal."""
from __future__ import annotations
import json, os, sqlite3, time, uuid
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r15_trust.db"
DB.parent.mkdir(exist_ok=True)
MAX_ACTIONS_PER_OWNER=max(200,min(10000,int(os.getenv("RONN_TRUST_MAX_ACTIONS_PER_OWNER","2000") or "2000")))
MAX_JSON_CHARS=max(20000,min(1000000,int(os.getenv("RONN_TRUST_JSON_MAX_CHARS","120000") or "120000")))

def _db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS actions(
      id TEXT PRIMARY KEY, owner TEXT, action TEXT, target TEXT, risk TEXT,
      reversible INTEGER, before_state TEXT, after_state TEXT, evidence TEXT,
      status TEXT, created_at INTEGER, updated_at INTEGER)""")
    c.commit(); return c

def _prune_owner(c, owner):
    c.execute(
        """DELETE FROM actions
           WHERE owner=? AND id NOT IN (
             SELECT id FROM actions WHERE owner=?
             ORDER BY updated_at DESC,created_at DESC,rowid DESC LIMIT ?
           )""",
        (str(owner),str(owner),MAX_ACTIONS_PER_OWNER),
    )


def _bounded_value(value,string_limit=16000,item_limit=100,depth=0):
    if depth>=8:
        return {"_ronn_truncated":True,"reason":"max_depth"}
    if value is None or isinstance(value,(bool,int,float)):
        return value
    if isinstance(value,str):
        if len(value)<=string_limit:
            return value
        return value[:max(0,string_limit-24)]+"...[RONN truncated]"
    if isinstance(value,dict):
        out={}
        items=list(value.items())
        for key,val in items[:item_limit]:
            out[str(key)[:240]]=_bounded_value(val,string_limit,item_limit,depth+1)
        if len(items)>item_limit:
            out["_ronn_truncated_items"]=len(items)-item_limit
        return out
    if isinstance(value,(list,tuple)):
        out=[_bounded_value(v,string_limit,item_limit,depth+1) for v in list(value)[:item_limit]]
        if len(value)>item_limit:
            out.append({"_ronn_truncated_items":len(value)-item_limit})
        return out
    return _bounded_value(str(value),string_limit,item_limit,depth+1)


def _pack_json(value):
    """Return (valid_json_text, truncated)."""
    if value is None:
        return "",False
    try:
        raw=json.dumps(value,ensure_ascii=False)
    except Exception:
        value={"text":str(value)}
        raw=json.dumps(value,ensure_ascii=False)
    if len(raw)<=MAX_JSON_CHARS:
        return raw,False
    for string_limit,item_limit in (
        (16000,100),(8000,80),(4000,60),(1600,45),(600,30),(240,20),
    ):
        bounded=_bounded_value(value,string_limit,item_limit)
        raw=json.dumps(bounded,ensure_ascii=False)
        if len(raw)<=MAX_JSON_CHARS:
            return raw,True
    fallback={
        "_ronn_truncated":True,
        "reason":"serialized_state_exceeded_limit",
        "preview":str(value)[:max(0,MAX_JSON_CHARS//2)],
    }
    text=json.dumps(fallback,ensure_ascii=False)
    while len(text)>MAX_JSON_CHARS and fallback.get("preview"):
        preview=fallback["preview"]
        shrink=max(64,len(preview)//4)
        fallback["preview"]=preview[:-shrink] if shrink<len(preview) else ""
        text=json.dumps(fallback,ensure_ascii=False)
    if len(text)>MAX_JSON_CHARS:
        fallback.pop("preview",None)
        text=json.dumps(fallback,ensure_ascii=False)
    return text,True


def checkpoint(owner,action,target,before=None,after=None,risk="low",reversible=True,evidence=None):
    aid="act_"+uuid.uuid4().hex[:18]; now=int(time.time())
    before_json,before_truncated=_pack_json(before)
    after_json,_after_truncated=_pack_json(after)
    evidence_json,_evidence_truncated=_pack_json(evidence)
    # A rollback is only safe when the exact before-state was retained.
    reversible_exact=bool(reversible and not before_truncated)
    with _db() as c:
        c.execute("""INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (aid,str(owner)[:120],str(action)[:120],str(target)[:300],str(risk)[:20],
           1 if reversible_exact else 0,before_json,after_json,evidence_json,
           "completed",now,now))
        _prune_owner(c,owner)
        c.commit()
    out=get(aid)
    if out is not None:
        out["state_truncated"]=bool(before_truncated or _after_truncated or _evidence_truncated)
        out["requested_reversible"]=bool(reversible)
    return out

def add_evidence(action_id,evidence):
    with _db() as c:
        row=c.execute("SELECT evidence FROM actions WHERE id=?",(action_id,)).fetchone()
        if not row: return False
        try: current=json.loads(row["evidence"] or "[]")
        except Exception: current=[]
        if not isinstance(current,list): current=[current]
        current.append(evidence)

        # Prefer the newest evidence when the journal reaches its byte budget.
        text,truncated=_pack_json(current)
        if truncated and len(current)>1:
            while len(current)>1:
                current=current[1:]
                text,truncated=_pack_json(current)
                if not truncated:
                    break
        c.execute("UPDATE actions SET evidence=?,updated_at=? WHERE id=?",
                  (text,int(time.time()),action_id))
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
    evidence_json,_truncated=_pack_json(evidence)
    with _db() as c:
        c.execute("UPDATE actions SET status='rolled_back',evidence=?,updated_at=? WHERE id=?",
          (evidence_json,int(time.time()),str(action_id)))
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
    return {"actions":int(total),"rolled_back":int(rb),"max_actions_per_owner":MAX_ACTIONS_PER_OWNER}
