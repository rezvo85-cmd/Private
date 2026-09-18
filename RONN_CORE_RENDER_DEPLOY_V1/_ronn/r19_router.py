"""RONN R19 evidence-driven model router."""
from __future__ import annotations
import sqlite3, time
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r19_router.db"
DB.parent.mkdir(exist_ok=True)

def _db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS outcomes(
      profile TEXT,model TEXT,wins REAL,losses REAL,latency_sum REAL,samples INTEGER,updated_at INTEGER,
      PRIMARY KEY(profile,model))""")
    c.commit();return c

def record(profile,model,success,latency_s=0.0,weight=1.0):
    if not model:return
    p=str(profile or "chat")[:50];m=str(model)[:180];w=max(.1,min(float(weight),3.0));now=int(time.time())
    with _db() as c:
        c.execute("""INSERT INTO outcomes VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(profile,model) DO UPDATE SET
          wins=outcomes.wins+excluded.wins,losses=outcomes.losses+excluded.losses,
          latency_sum=outcomes.latency_sum+excluded.latency_sum,samples=outcomes.samples+1,updated_at=excluded.updated_at""",
          (p,m,w if success else 0,w if not success else 0,max(0,float(latency_s)),1,now));c.commit()

def score(profile,model):
    with _db() as c:r=c.execute("SELECT * FROM outcomes WHERE profile=? AND model=?",(str(profile),str(model))).fetchone()
    if not r:return {"score":0.5,"samples":0,"avg_latency":None}
    wins=float(r["wins"]);loss=float(r["losses"]);samples=int(r["samples"])
    quality=(wins+1)/(wins+loss+2)
    lat=float(r["latency_sum"])/samples if samples else 0
    # Only a light latency penalty; correctness dominates.
    s=max(0,min(1,quality-min(.08,lat/300)))
    return {"score":round(s,4),"samples":samples,"avg_latency":round(lat,3)}

def choose(profile,candidates,default):
    rows=[]
    for m in candidates:
        s=score(profile,m);rows.append((s["score"],s["samples"],m))
    mature=[x for x in rows if x[1]>=3]
    if not mature:return default
    mature.sort(reverse=True)
    best=mature[0]
    default_score=score(profile,default)
    return best[2] if best[0]>=default_score["score"]+.03 else default

def report(profile=None):
    with _db() as c:
        if profile:rows=c.execute("SELECT * FROM outcomes WHERE profile=? ORDER BY samples DESC",(str(profile),)).fetchall()
        else:rows=c.execute("SELECT * FROM outcomes ORDER BY samples DESC LIMIT 80").fetchall()
    out=[]
    for r in rows:
        s=score(r["profile"],r["model"]);out.append({"profile":r["profile"],"model":r["model"],**s})
    return out
