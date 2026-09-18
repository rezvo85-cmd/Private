"""RONN R14 persistent project knowledge graph."""
from __future__ import annotations
import re, sqlite3, time
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r14_knowledge_graph.db"
DB.parent.mkdir(exist_ok=True)

STOP={"the","and","for","with","that","this","from","your","you","are","was","were","have","has","had","but","not","all","can","will","into","about","just","use","using","make","made","fix","get"}

def _db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS nodes(
        id INTEGER PRIMARY KEY, owner TEXT, project TEXT, kind TEXT, label TEXT,
        detail TEXT, weight REAL DEFAULT 1, updated_at INTEGER,
        UNIQUE(owner,project,kind,label))""")
    c.execute("""CREATE TABLE IF NOT EXISTS edges(
        id INTEGER PRIMARY KEY, owner TEXT, project TEXT, src TEXT, relation TEXT,
        dst TEXT, weight REAL DEFAULT 1, updated_at INTEGER,
        UNIQUE(owner,project,src,relation,dst))""")
    c.commit()
    return c

def _terms(text):
    words=re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}",str(text or ""))
    out=[]
    for w in words:
        if w.lower() in STOP: continue
        if w.lower() not in {x.lower() for x in out}: out.append(w[:90])
        if len(out)>=28: break
    return out

def _kind(label,text):
    low=(str(text or "")+" "+label).lower()
    if any(x in low for x in ("error","bug","broken","failure","issue")): return "problem"
    if any(x in low for x in ("decide","decision","keep","preserve","must","require")): return "decision"
    if any(x in low for x in (".py",".js",".ts",".json",".html",".css",".lua",".luau","file")): return "artifact"
    if any(x in low for x in ("api","service","module","backend","frontend","database","route")): return "component"
    return "concept"

def ingest(owner, project, text, source="conversation"):
    owner=str(owner or "default")[:120]; project=str(project or "default")[:180]
    clean=re.sub(r"\s+"," ",str(text or "")).strip()
    if not clean: return {"nodes":0,"edges":0}
    labels=_terms(clean)
    now=int(time.time()); nodes=0; edges=0
    with _db() as c:
        for label in labels:
            kind=_kind(label,clean)
            c.execute("""INSERT INTO nodes(owner,project,kind,label,detail,weight,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,project,kind,label)
                DO UPDATE SET detail=excluded.detail,weight=min(10,nodes.weight+0.15),updated_at=excluded.updated_at""",
                (owner,project,kind,label,(source+": "+clean)[:1000],1.0,now))
            nodes+=1
        anchor=labels[0] if labels else ""
        for label in labels[1:12]:
            c.execute("""INSERT INTO edges(owner,project,src,relation,dst,weight,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,project,src,relation,dst)
                DO UPDATE SET weight=min(10,edges.weight+0.1),updated_at=excluded.updated_at""",
                (owner,project,anchor,"related_to",label,1.0,now))
            edges+=1
        c.commit()
    return {"nodes":nodes,"edges":edges}

def ingest_files(owner, project, files):
    total={"nodes":0,"edges":0}
    for f in list(files or [])[:20]:
        name=getattr(f,"name","file")
        content=getattr(f,"content","")
        r=ingest(owner,project,f"{name}\n{content[:8000]}",source="file")
        total["nodes"]+=r["nodes"]; total["edges"]+=r["edges"]
    return total

def context(owner, project, query, limit=10):
    q={x.lower() for x in _terms(query)}
    if not q: return ""
    with _db() as c:
        rows=c.execute("SELECT kind,label,detail,weight,updated_at FROM nodes WHERE owner=? AND project=? ORDER BY weight DESC,updated_at DESC LIMIT 180",(str(owner),str(project))).fetchall()
    scored=[]
    for r in rows:
        label=str(r["label"]); detail=str(r["detail"])
        words={x.lower() for x in _terms(label+" "+detail)}
        overlap=len(q & words)
        if overlap: scored.append((overlap*5+float(r["weight"] or 1),dict(r)))
    scored.sort(key=lambda x:x[0],reverse=True)
    return "\n".join(f"- [{r['kind']}] {r['label']}: {r['detail'][:420]}" for _,r in scored[:max(1,min(int(limit),20))])

def stats(owner=None):
    with _db() as c:
        if owner:
            n=c.execute("SELECT COUNT(*) n FROM nodes WHERE owner=?",(str(owner),)).fetchone()["n"]
            e=c.execute("SELECT COUNT(*) n FROM edges WHERE owner=?",(str(owner),)).fetchone()["n"]
        else:
            n=c.execute("SELECT COUNT(*) n FROM nodes").fetchone()["n"]
            e=c.execute("SELECT COUNT(*) n FROM edges").fetchone()["n"]
    return {"nodes":int(n),"edges":int(e)}
