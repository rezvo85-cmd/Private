"""RONN R19 long-context compression, evidence planning and failure memory."""
from __future__ import annotations
import re, sqlite3, time, uuid
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r19_failures.db"
DB.parent.mkdir(exist_ok=True)

def _db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS failures(
      id TEXT PRIMARY KEY,owner TEXT,domain TEXT,lesson TEXT,created_at INTEGER,use_count INTEGER DEFAULT 0)""")
    c.commit();return c

def conversation_digest(history,max_chars=9000):
    items=[]
    for x in list(history or [])[:-8]:
        role=x.get("role") if isinstance(x,dict) else None
        content=x.get("content") if isinstance(x,dict) else None
        if role not in {"user","assistant"} or not isinstance(content,str):continue
        clean=re.sub(r"\s+"," ",content).strip()
        if not clean:continue
        # Prefer explicit constraints/decisions and compact first sentences.
        important=any(k in clean.lower() for k in ("must","don't","do not","keep","remember","decided","error","failed","works","doesn't","cannot","project","name"))
        if important or role=="user":
            items.append(f"{role}: {clean[:650]}")
    text="\n".join(items[-18:])
    return text[-max_chars:]

def evidence_plan(message,has_files=False,has_images=False):
    low=str(message or "").lower();sources=[]
    if any(x in low for x in ("latest","today","current","news","price","version","right now")):sources.append("live_research")
    if has_files:sources.append("project_files")
    if has_images:sources.append("vision")
    if any(x in low for x in ("remember","before","previous","continue","project")):sources.append("memory_graph")
    if any(x in low for x in ("calculate","equation","code","debug","test","verify")):sources.append("deterministic_tools")
    if not sources:sources.append("model_knowledge")
    return {"sources":sources,"needs_live":"live_research" in sources,"needs_verification":any(x in sources for x in ("live_research","deterministic_tools"))}

def record_failure(owner,lesson,domain="general"):
    clean=re.sub(r"\s+"," ",str(lesson or "")).strip()
    if len(clean)<8:return None
    fid="fail_"+uuid.uuid4().hex[:16]
    with _db() as c:
        c.execute("INSERT INTO failures VALUES(?,?,?,?,?,0)",(fid,str(owner)[:120],str(domain)[:60],clean[:1500],int(time.time())));c.commit()
    return fid

def relevant_failures(owner,query,limit=5):
    words={x for x in re.findall(r"[a-z0-9']+",str(query or "").lower()) if len(x)>3}
    with _db() as c:rows=c.execute("SELECT * FROM failures WHERE owner=? ORDER BY created_at DESC LIMIT 120",(str(owner),)).fetchall()
    scored=[]
    for r in rows:
        rw={x for x in re.findall(r"[a-z0-9']+",r["lesson"].lower()) if len(x)>3}
        ov=len(words&rw)
        if ov:scored.append((ov,dict(r)))
    scored.sort(key=lambda x:x[0],reverse=True);picked=[r for _,r in scored[:limit]]
    if picked:
        with _db() as c:
            for r in picked:c.execute("UPDATE failures SET use_count=use_count+1 WHERE id=?",(r["id"],))
            c.commit()
    return picked
