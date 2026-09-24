import sqlite3, time, json, hashlib
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"experience.sqlite3"
DB.parent.mkdir(parents=True,exist_ok=True)

def _db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS runs(
      request_id TEXT PRIMARY KEY,
      owner TEXT, project_id TEXT, prompt_hash TEXT, profile TEXT,
      route TEXT, model TEXT, strategy TEXT, difficulty INTEGER,
      latency REAL DEFAULT 0, response_chars INTEGER DEFAULT 0,
      status TEXT DEFAULT 'started', created REAL, finished REAL
    );
    CREATE TABLE IF NOT EXISTS feedback(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      request_id TEXT, rating INTEGER, note TEXT DEFAULT '', created REAL,
      UNIQUE(request_id)
    );
    CREATE TABLE IF NOT EXISTS lessons(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      domain TEXT, signature TEXT, lesson TEXT, confidence REAL DEFAULT .6,
      uses INTEGER DEFAULT 1, updated REAL,
      UNIQUE(domain,signature)
    );
    CREATE TABLE IF NOT EXISTS contradictions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id TEXT, left_claim TEXT, right_claim TEXT,
      status TEXT DEFAULT 'unresolved', created REAL
    );
    CREATE TABLE IF NOT EXISTS portable_outcomes(
      model TEXT NOT NULL, profile TEXT NOT NULL,
      good INTEGER NOT NULL DEFAULT 0, bad INTEGER NOT NULL DEFAULT 0,
      updated REAL NOT NULL DEFAULT 0,
      PRIMARY KEY(model,profile)
    );
    """)
    return c

def start_run(request_id,owner,project_id,prompt,profile,route,model,strategy,difficulty):
    with _db() as c:
        c.execute("""INSERT OR REPLACE INTO runs
        (request_id,owner,project_id,prompt_hash,profile,route,model,strategy,difficulty,created,status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (request_id,owner,project_id,hashlib.sha256((prompt or "").encode()).hexdigest()[:20],
         profile,route,model,strategy,int(difficulty),time.time(),"started"))

def finish_run(request_id,latency,response_chars,status="complete",model=None,route=None):
    with _db() as c:
        if model is not None or route is not None:
            current=c.execute("SELECT model,route FROM runs WHERE request_id=?",(request_id,)).fetchone()
            final_model=(model if model is not None else (current["model"] if current else ""))
            final_route=(route if route is not None else (current["route"] if current else ""))
            c.execute("UPDATE runs SET latency=?,response_chars=?,status=?,finished=?,model=?,route=? WHERE request_id=?",
                      (float(latency),int(response_chars),status,time.time(),final_model,final_route,request_id))
        else:
            c.execute("UPDATE runs SET latency=?,response_chars=?,status=?,finished=? WHERE request_id=?",
                      (float(latency),int(response_chars),status,time.time(),request_id))

def add_feedback(request_id,rating,note="",owner=None):
    """Record feedback only for an existing run, optionally enforcing ownership."""
    rating=1 if int(rating)>0 else -1
    request_id=str(request_id)
    with _db() as c:
        if owner is None:
            run=c.execute("SELECT * FROM runs WHERE request_id=?",(request_id,)).fetchone()
        else:
            run=c.execute(
                "SELECT * FROM runs WHERE request_id=? AND owner=?",
                (request_id,str(owner)),
            ).fetchone()
        if not run:
            return None
        c.execute("""INSERT INTO feedback(request_id,rating,note,created) VALUES(?,?,?,?)
        ON CONFLICT(request_id) DO UPDATE SET rating=excluded.rating,note=excluded.note,created=excluded.created""",
        (request_id,rating,(note or "")[:1200],time.time()))
    return dict(run)

def observed_model_scores():
    with _db() as c:
        rows=c.execute("""
        SELECT r.model,r.profile,
          COUNT(f.id) ratings,
          AVG(f.rating) avg_rating,
          AVG(r.latency) avg_latency
        FROM runs r JOIN feedback f ON f.request_id=r.request_id
        GROUP BY r.model,r.profile
        HAVING COUNT(f.id)>=1
        ORDER BY avg_rating DESC,avg_latency ASC
        """).fetchall()
    return [dict(x) for x in rows]

def learn_lesson(domain,signature,lesson,confidence=.65):
    with _db() as c:
        c.execute("""INSERT INTO lessons(domain,signature,lesson,confidence,uses,updated)
        VALUES(?,?,?,?,1,?) ON CONFLICT(domain,signature) DO UPDATE SET
        lesson=excluded.lesson,confidence=max(lessons.confidence,excluded.confidence),
        uses=lessons.uses+1,updated=excluded.updated""",
        (domain,signature[:200],lesson[:3000],float(confidence),time.time()))

def retrieve_lessons(domain,limit=8):
    with _db() as c:
        rows=c.execute("SELECT * FROM lessons WHERE domain IN (?, 'general') ORDER BY confidence DESC,uses DESC,updated DESC LIMIT ?",
                       (domain,int(limit))).fetchall()
    return [dict(x) for x in rows]

def ingest_portable_outcomes(snapshot):
    """Merge a bounded device-side aggregate of Good/Improve feedback.

    The snapshot contains counts only, never prompts or answer text. Newer device
    aggregates replace older copies for the same model/profile to avoid double
    counting the same clicks after a backend redeploy.
    """
    if not isinstance(snapshot,dict):
        return {"ok":False,"rows":0}
    rows=list(snapshot.get("rows") or [])[:50]
    accepted=0
    now=time.time()
    with _db() as c:
        for row in rows:
            if not isinstance(row,dict):
                continue
            model=str(row.get("model") or "").strip()[:220]
            profile=str(row.get("profile") or "").strip().lower()[:40]
            if not model or not profile:
                continue
            try:
                good=max(0,min(100,int(row.get("good") or 0)))
                bad=max(0,min(100,int(row.get("bad") or 0)))
                updated=float(row.get("updated") or now)
            except Exception:
                continue
            if updated>10**12:
                updated/=1000.0
            updated=max(0,min(updated,now+86400))
            old=c.execute(
                "SELECT updated FROM portable_outcomes WHERE model=? AND profile=?",
                (model,profile),
            ).fetchone()
            if old and float(old["updated"] or 0)>updated:
                continue
            c.execute("""INSERT INTO portable_outcomes(model,profile,good,bad,updated)
                VALUES(?,?,?,?,?) ON CONFLICT(model,profile) DO UPDATE SET
                good=excluded.good,bad=excluded.bad,updated=excluded.updated""",
                (model,profile,good,bad,updated))
            accepted+=1
    return {"ok":True,"rows":accepted}


def _feedback_row(model,profile,min_ratings=3):
    model=str(model or "")
    profile=str(profile or "").lower()
    with _db() as c:
        portable=c.execute(
            "SELECT good,bad,updated FROM portable_outcomes WHERE model=? AND profile=?",
            (model,profile),
        ).fetchone()
        if portable:
            good=int(portable["good"] or 0);bad=int(portable["bad"] or 0)
            total=good+bad
            updated=float(portable["updated"] or 0)
            fresh=updated >= time.time()-(60*86400)
            if fresh and total>=int(min_ratings):
                return {
                    "ratings":total,
                    "avg_rating":(good-bad)/max(1,total),
                    "source":"device_aggregate",
                    "updated":updated,
                }
        row=c.execute("""SELECT COUNT(f.id) ratings, AVG(f.rating) avg_rating
            FROM runs r JOIN feedback f ON f.request_id=r.request_id
            WHERE r.model=? AND r.profile=?""",(model,profile)).fetchone()
    ratings=int(row["ratings"] or 0) if row else 0
    if ratings<int(min_ratings):
        return None
    return {
        "ratings":ratings,
        "avg_rating":float(row["avg_rating"] or 0),
        "source":"server_feedback",
        "updated":0,
    }


def profile_feedback_signal(models,profile,min_ratings=3):
    """Profile-specific outcome signal for safe adaptive routing.

    Repeated negative outcomes may demote one model independently. Positive
    comparative reordering is enabled only after every candidate has enough
    ratings for the same profile.
    """
    models=[str(x) for x in models if x]
    scores={}
    for model in models:
        row=_feedback_row(model,profile,min_ratings)
        if not row:
            continue
        avg=float(row["avg_rating"])
        penalty=3 if avg<=-.5 else (1 if avg<0 else 0)
        scores[model]={**row,"penalty":penalty}
    ready=bool(models) and all(m in scores for m in models)
    return {
        "profile":str(profile or "chat").lower(),
        "ready":ready,
        "candidate_count":len(models),
        "measured_count":len(scores),
        "scores":scores,
        "min_ratings":int(min_ratings),
    }


def portable_outcome_status():
    with _db() as c:
        rows=c.execute("""SELECT model,profile,good,bad,updated
                          FROM portable_outcomes ORDER BY updated DESC LIMIT 50""").fetchall()
    return {"rows":[dict(x) for x in rows],"count":len(rows)}


def stats():
    with _db() as c:
        runs=c.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"]
        rated=c.execute("SELECT COUNT(*) n FROM feedback").fetchone()["n"]
        complete=c.execute("SELECT COUNT(*) n FROM runs WHERE status='complete'").fetchone()["n"]
    return {"runs":runs,"completed":complete,"rated":rated,"model_scores":observed_model_scores()}


def model_feedback_penalty(model, min_ratings=2):
    """Observed user feedback signal. Requires multiple ratings before affecting routing."""
    with _db() as c:
        row=c.execute("""
        SELECT COUNT(f.id) ratings, AVG(f.rating) avg_rating
        FROM runs r JOIN feedback f ON f.request_id=r.request_id
        WHERE r.model=?
        """,(model,)).fetchone()
    if not row or int(row["ratings"] or 0) < int(min_ratings): return 0
    avg=float(row["avg_rating"] or 0)
    if avg <= -0.5: return 4
    if avg < 0: return 2
    return 0
