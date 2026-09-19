import sqlite3, json, time, hashlib, re
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "project_brain.sqlite3"
DB.parent.mkdir(parents=True, exist_ok=True)

def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS projects(
      project_id TEXT PRIMARY KEY, name TEXT, summary TEXT DEFAULT '',
      created REAL, updated REAL
    );
    CREATE TABLE IF NOT EXISTS facts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, kind TEXT,
      key TEXT, value TEXT, confidence REAL DEFAULT .8, source TEXT DEFAULT '',
      created REAL, updated REAL,
      UNIQUE(project_id,kind,key)
    );
    CREATE TABLE IF NOT EXISTS relations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT,
      src TEXT, relation TEXT, dst TEXT, evidence TEXT DEFAULT '',
      updated REAL, UNIQUE(project_id,src,relation,dst)
    );
    CREATE TABLE IF NOT EXISTS attempts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, task_id TEXT,
      stage TEXT, status TEXT, detail TEXT, created REAL
    );
    CREATE TABLE IF NOT EXISTS model_scores(
      model TEXT, domain TEXT, score REAL, latency REAL DEFAULT 0,
      samples INTEGER DEFAULT 0, updated REAL,
      PRIMARY KEY(model,domain)
    );
    CREATE TABLE IF NOT EXISTS fact_history(
      id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, kind TEXT, key TEXT,
      old_value TEXT, new_value TEXT, source TEXT DEFAULT '', changed REAL
    );
    CREATE INDEX IF NOT EXISTS idx_fact_history_project ON fact_history(project_id,changed DESC);
    """)
    return c

def project_id(name="default"):
    return hashlib.sha256((name or "default").encode()).hexdigest()[:16]

def ensure_project(name="default"):
    pid=project_id(name); now=time.time()
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO projects(project_id,name,created,updated) VALUES(?,?,?,?)",(pid,name,now,now))
        c.execute("UPDATE projects SET updated=? WHERE project_id=?",(now,pid))
    return pid

def remember(pid, kind, key, value, confidence=.8, source="ronn"):
    now=time.time(); value=str(value)[:12000]
    with _db() as c:
        old=c.execute("SELECT value,source FROM facts WHERE project_id=? AND kind=? AND key=?",(pid,kind,key)).fetchone()
        if old and old["value"] != value:
            c.execute("INSERT INTO fact_history(project_id,kind,key,old_value,new_value,source,changed) VALUES(?,?,?,?,?,?,?)",
                      (pid,kind,key,old["value"][:12000],value,(source or "")[:200],now))
        c.execute("""INSERT INTO facts(project_id,kind,key,value,confidence,source,created,updated)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,kind,key) DO UPDATE SET
        value=excluded.value,confidence=excluded.confidence,source=excluded.source,updated=excluded.updated""",
        (pid,kind,key,value,float(confidence),source,now,now))

def relate(pid, src, relation, dst, evidence=""):
    with _db() as c:
        c.execute("""INSERT INTO relations(project_id,src,relation,dst,evidence,updated)
        VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,src,relation,dst) DO UPDATE SET evidence=excluded.evidence,updated=excluded.updated""",
        (pid,src[:300],relation[:100],dst[:300],evidence[:2000],time.time()))

def record_attempt(pid, task_id, stage, status, detail=""):
    with _db() as c:
        c.execute("INSERT INTO attempts(project_id,task_id,stage,status,detail,created) VALUES(?,?,?,?,?,?)",
                  (pid,task_id,stage,status,detail[:8000],time.time()))

def retrieve(pid, query="", limit=24):
    q=(query or "").lower()
    words={w for w in re.findall(r"[a-z0-9_]{3,}",q)}
    now=time.time()
    with _db() as c:
        rows=c.execute("SELECT * FROM facts WHERE project_id=? ORDER BY updated DESC LIMIT 220",(pid,)).fetchall()
        rel=c.execute("SELECT * FROM relations WHERE project_id=? ORDER BY updated DESC LIMIT 160",(pid,)).fetchall()
        hist=c.execute("SELECT kind,key,old_value,new_value,source,changed FROM fact_history WHERE project_id=? ORDER BY changed DESC LIMIT 30",(pid,)).fetchall()
    scored=[]
    for r in rows:
        hay=(r["key"]+" "+r["value"]+" "+r["kind"]).lower()
        overlap=sum(1 for w in words if w in hay)
        kind_bonus=2.5 if r["kind"] in ("decision","constraint","failure") else 0
        confidence=float(r["confidence"] or .7)
        age_days=max(0,(now-float(r["updated"] or now))/86400)
        recency=max(0,1.5-min(1.5,age_days/45))
        score=overlap*3+kind_bonus+confidence+recency
        scored.append((score,r))
    scored.sort(key=lambda x:x[0], reverse=True)
    return {
      "facts":[dict(r) for _,r in scored[:limit]],
      "relations":[dict(r) for r in rel[:limit]],
      "history":[dict(r) for r in hist[:min(limit,12)]],
    }

def ingest_project_text(pid, text, source="context"):
    text=(text or "")[:100000]
    # Safe heuristic extraction: explicit conventions/decisions/failures and code relationships.
    for line in text.splitlines():
        s=line.strip()
        low=s.lower()
        if not s or len(s)>1000: continue
        if any(x in low for x in ("must ","should ","requirement","constraint")):
            remember(pid,"constraint",hashlib.md5(s.encode()).hexdigest()[:10],s,.75,source)
        if any(x in low for x in ("decided","architecture","convention","pattern")):
            remember(pid,"decision",hashlib.md5(s.encode()).hexdigest()[:10],s,.72,source)
        if any(x in low for x in ("error","failed","broken","bug")):
            remember(pid,"failure",hashlib.md5(s.encode()).hexdigest()[:10],s,.68,source)
    for m in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*(?:Service|Controller|Module|Manager|Handler))', text):
        remember(pid,"symbol",m.group(1),m.group(1),.65,source)
    for m in re.finditer(r'require\s*\([^)]*?([A-Za-z_][A-Za-z0-9_]*)\s*\)', text):
        relate(pid,"code","requires",m.group(1),"require() reference")

def brain_context(pid, query):
    data=retrieve(pid,query)
    if not data["facts"] and not data["relations"] and not data.get("history"): return ""
    lines=["PERSISTENT PROJECT BRAIN (retrieved context; do not treat guesses as facts):"]
    for f in data["facts"]:
        lines.append(f'- [{f["kind"]}] {f["key"]}: {f["value"]}')
    for r in data["relations"]:
        lines.append(f'- [relation] {r["src"]} --{r["relation"]}--> {r["dst"]}')
    for h in data.get("history",[])[:8]:
        lines.append(f'- [changed {h["kind"]}] {h["key"]}: previous={h["old_value"]} -> current={h["new_value"]}')
    return "\n".join(lines)[:18000]

def score_model(model, domain, score, latency=0):
    now=time.time()
    with _db() as c:
        old=c.execute("SELECT * FROM model_scores WHERE model=? AND domain=?",(model,domain)).fetchone()
        if old:
            n=old["samples"]+1
            avg=(old["score"]*old["samples"]+score)/n
            lat=(old["latency"]*old["samples"]+latency)/n
            c.execute("UPDATE model_scores SET score=?,latency=?,samples=?,updated=? WHERE model=? AND domain=?",
                      (avg,lat,n,now,model,domain))
        else:
            c.execute("INSERT INTO model_scores VALUES(?,?,?,?,?,?)",(model,domain,score,latency,1,now))

def set_model_score(model, domain, score, latency=0, samples=1):
    """Replace a model/domain score with a fresh measured window."""
    now=time.time()
    with _db() as c:
        c.execute("""INSERT INTO model_scores(model,domain,score,latency,samples,updated)
        VALUES(?,?,?,?,?,?) ON CONFLICT(model,domain) DO UPDATE SET
        score=excluded.score,latency=excluded.latency,samples=excluded.samples,updated=excluded.updated""",
        (str(model),str(domain),float(score),float(latency),max(0,int(samples)),now))


def model_arena(domain=None):
    with _db() as c:
        if domain:
            rows=c.execute("SELECT * FROM model_scores WHERE domain=? ORDER BY score DESC,latency ASC",(domain,)).fetchall()
        else:
            rows=c.execute("SELECT * FROM model_scores ORDER BY domain,score DESC,latency ASC").fetchall()
    return [dict(r) for r in rows]



ARENA_SCORE_DOMAINS={"main","instruction","reasoning","coding","certification"}


def export_model_scores(models=None, max_age_days=30):
    """Portable objective Arena evidence. Contains no prompts or user content."""
    allow={str(x) for x in (models or []) if x}
    cutoff=time.time()-max(1,min(int(max_age_days),90))*86400
    with _db() as c:
        rows=c.execute(
            "SELECT model,domain,score,latency,samples,updated FROM model_scores WHERE updated>=? ORDER BY updated DESC LIMIT 120",
            (cutoff,),
        ).fetchall()
    out=[]
    for row in rows:
        d=dict(row)
        if d.get("domain") not in ARENA_SCORE_DOMAINS:
            continue
        if allow and str(d.get("model") or "") not in allow:
            continue
        out.append({
            "model":str(d.get("model") or "")[:220],
            "domain":str(d.get("domain") or "")[:40],
            "score":round(max(0.0,min(100.0,float(d.get("score") or 0))),4),
            "latency":round(max(0.0,min(120.0,float(d.get("latency") or 0))),4),
            "samples":max(0,min(100,int(d.get("samples") or 0))),
            "updated":float(d.get("updated") or 0),
        })
    return {
        "version":"R23-ARENA-SNAPSHOT-1",
        "rows":out[:100],
        "exported_at":int(time.time()),
    }


def import_model_scores(snapshot, allowed_models=None, max_age_days=30):
    """Restore newer objective Arena windows after an ephemeral backend redeploy."""
    if not isinstance(snapshot,dict):
        return {"ok":False,"reason":"invalid_snapshot","imported":0,"skipped":0}
    allowed={str(x) for x in (allowed_models or []) if x}
    rows=list(snapshot.get("rows") or [])[:100]
    now=time.time()
    cutoff=now-max(1,min(int(max_age_days),90))*86400
    imported=0;skipped=0
    with _db() as c:
        for row in rows:
            if not isinstance(row,dict):
                skipped+=1;continue
            model=str(row.get("model") or "").strip()[:220]
            domain=str(row.get("domain") or "").strip().lower()[:40]
            if not model or domain not in ARENA_SCORE_DOMAINS or (allowed and model not in allowed):
                skipped+=1;continue
            try:
                score=max(0.0,min(100.0,float(row.get("score") or 0)))
                latency=max(0.0,min(120.0,float(row.get("latency") or 0)))
                samples=max(0,min(100,int(row.get("samples") or 0)))
                updated=float(row.get("updated") or 0)
            except Exception:
                skipped+=1;continue
            if samples<=0 or updated<cutoff or updated>now+3600:
                skipped+=1;continue
            old=c.execute(
                "SELECT updated FROM model_scores WHERE model=? AND domain=?",
                (model,domain),
            ).fetchone()
            if old and float(old["updated"] or 0)>=updated:
                skipped+=1;continue
            c.execute("""INSERT INTO model_scores(model,domain,score,latency,samples,updated)
                VALUES(?,?,?,?,?,?) ON CONFLICT(model,domain) DO UPDATE SET
                score=excluded.score,latency=excluded.latency,samples=excluded.samples,updated=excluded.updated""",
                (model,domain,score,latency,samples,updated))
            imported+=1
    return {"ok":True,"imported":imported,"skipped":skipped,"version":"R23-ARENA-SNAPSHOT-1"}


def export_project(pid, fact_limit=80, relation_limit=80):
    """Bounded portable snapshot for client/cloud durability fallbacks."""
    with _db() as c:
        project=c.execute("SELECT * FROM projects WHERE project_id=?",(pid,)).fetchone()
        facts=c.execute(
            "SELECT kind,key,value,confidence,source,created,updated FROM facts WHERE project_id=? ORDER BY updated DESC LIMIT ?",
            (pid,max(1,min(int(fact_limit),200))),
        ).fetchall()
        relations=c.execute(
            "SELECT src,relation,dst,evidence,updated FROM relations WHERE project_id=? ORDER BY updated DESC LIMIT ?",
            (pid,max(1,min(int(relation_limit),200))),
        ).fetchall()
    portable_facts=[]
    for x in facts:
        d=dict(x)
        d["value"]=str(d.get("value") or "")[:1600]
        d["source"]=str(d.get("source") or "")[:160]
        portable_facts.append(d)
    portable_relations=[]
    for x in relations:
        d=dict(x)
        d["src"]=str(d.get("src") or "")[:220]
        d["relation"]=str(d.get("relation") or "")[:80]
        d["dst"]=str(d.get("dst") or "")[:220]
        d["evidence"]=str(d.get("evidence") or "")[:600]
        portable_relations.append(d)
    return {
        "version":"R23-PROJECT-SNAPSHOT-1",
        "project":{"name":(project["name"] if project else "")[:180],"summary":(project["summary"] if project else "")[:1200]},
        "facts":portable_facts,
        "relations":portable_relations,
        "exported_at":int(time.time()),
    }


def import_project(pid,snapshot,source="portable_snapshot"):
    """Merge a bounded portable snapshot into the local Project Brain.

    Newer/current local facts win when their update timestamp is newer. Snapshot
    content is treated as user/project context, never as system instructions.
    """
    if not isinstance(snapshot,dict):
        return {"ok":False,"reason":"invalid_snapshot","facts":0,"relations":0}
    facts=list(snapshot.get("facts") or [])[:200]
    relations=list(snapshot.get("relations") or [])[:200]
    imported_facts=0;imported_relations=0
    now=time.time()
    with _db() as c:
        for row in facts:
            if not isinstance(row,dict): continue
            kind=str(row.get("kind") or "context")[:40]
            key=str(row.get("key") or "")[:300]
            value=str(row.get("value") or "")[:12000]
            if not key or not value: continue
            confidence=max(.1,min(1.0,float(row.get("confidence") or .7)))
            incoming_updated=float(row.get("updated") or row.get("created") or 0)
            existing=c.execute(
                "SELECT value,updated FROM facts WHERE project_id=? AND kind=? AND key=?",
                (pid,kind,key),
            ).fetchone()
            if existing and float(existing["updated"] or 0) > incoming_updated:
                continue
            if existing and existing["value"] != value:
                c.execute(
                    "INSERT INTO fact_history(project_id,kind,key,old_value,new_value,source,changed) VALUES(?,?,?,?,?,?,?)",
                    (pid,kind,key,existing["value"][:12000],value,source[:200],now),
                )
            c.execute("""INSERT INTO facts(project_id,kind,key,value,confidence,source,created,updated)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,kind,key) DO UPDATE SET
                value=excluded.value,confidence=max(facts.confidence,excluded.confidence),
                source=excluded.source,updated=max(facts.updated,excluded.updated)""",
                (pid,kind,key,value,confidence,source[:200],incoming_updated or now,incoming_updated or now))
            imported_facts+=1

        for row in relations:
            if not isinstance(row,dict): continue
            src=str(row.get("src") or "")[:300]
            relation=str(row.get("relation") or "")[:100]
            dst=str(row.get("dst") or "")[:300]
            evidence=str(row.get("evidence") or "")[:2000]
            if not src or not relation or not dst: continue
            updated=float(row.get("updated") or now)
            c.execute("""INSERT INTO relations(project_id,src,relation,dst,evidence,updated)
                VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,src,relation,dst) DO UPDATE SET
                evidence=excluded.evidence,updated=max(relations.updated,excluded.updated)""",
                (pid,src,relation,dst,evidence,updated))
            imported_relations+=1
    return {"ok":True,"facts":imported_facts,"relations":imported_relations}


def project_stats(pid):
    with _db() as c:
        facts=c.execute("SELECT COUNT(*) n FROM facts WHERE project_id=?",(pid,)).fetchone()["n"]
        relations=c.execute("SELECT COUNT(*) n FROM relations WHERE project_id=?",(pid,)).fetchone()["n"]
        changes=c.execute("SELECT COUNT(*) n FROM fact_history WHERE project_id=?",(pid,)).fetchone()["n"]
        failures=c.execute("SELECT COUNT(*) n FROM facts WHERE project_id=? AND kind='failure'",(pid,)).fetchone()["n"]
    return {"facts":facts,"relations":relations,"history_changes":changes,"known_failures":failures}
