"""RONN R14 persistent non-sensitive user preference model."""
from __future__ import annotations
import json, re, sqlite3, time
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r14_user_model.db"
DB.parent.mkdir(exist_ok=True)

def _db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS prefs(
      owner TEXT, key TEXT, value TEXT, confidence REAL, evidence INTEGER,
      updated_at INTEGER, PRIMARY KEY(owner,key))""")
    c.commit(); return c

RULES=[
 ("answer_length","short",("shorter","very short","keep it short","simple answer","dont yap","don't yap")),
 ("answer_length","detailed",("more detail","detailed","explain more","go deeper")),
 ("instructions","sequential",("step by step","one step at a time","simpler steps")),
 ("tone","natural",("less ai","sound natural","sound like me","not ai")),
 ("technical_style","direct",("just do it","do it","fix it","dont explain","don't explain")),
 ("verification","strict",("make sure","verify","check everything","reliable","dont say fixed","don't say fixed")),
]

def observe(owner,message):
    low=re.sub(r"\s+"," ",str(message or "").lower())
    updates=[]
    for key,value,terms in RULES:
        if any(t in low for t in terms):
            updates.append((key,value))
    now=int(time.time())
    with _db() as c:
        for key,value in updates:
            row=c.execute("SELECT value,confidence,evidence FROM prefs WHERE owner=? AND key=?",(owner,key)).fetchone()
            if row and row["value"]==value:
                conf=min(0.98,float(row["confidence"] or .7)+.04); ev=int(row["evidence"] or 0)+1
            else:
                conf=.72; ev=1
            c.execute("""INSERT INTO prefs(owner,key,value,confidence,evidence,updated_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(owner,key) DO UPDATE SET
              value=excluded.value,confidence=excluded.confidence,evidence=excluded.evidence,updated_at=excluded.updated_at""",
              (owner,key,value,conf,ev,now))
        c.commit()
    return updates

def profile(owner):
    with _db() as c:
        rows=c.execute("SELECT key,value,confidence,evidence FROM prefs WHERE owner=? ORDER BY confidence DESC,evidence DESC",(owner,)).fetchall()
    return {r["key"]:{"value":r["value"],"confidence":round(float(r["confidence"]),2),"evidence":int(r["evidence"])} for r in rows}

def directive(owner):
    p=profile(owner)
    if not p: return ""
    pairs=[f"{k}={v['value']}" for k,v in p.items() if v["confidence"]>=.7]
    return "RONN USER ADAPTATION (non-sensitive explicit preferences only): "+", ".join(pairs[:12])
