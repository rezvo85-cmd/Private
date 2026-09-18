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

def add_feedback(request_id,rating,note=""):
    rating=1 if int(rating)>0 else -1
    with _db() as c:
        c.execute("""INSERT INTO feedback(request_id,rating,note,created) VALUES(?,?,?,?)
        ON CONFLICT(request_id) DO UPDATE SET rating=excluded.rating,note=excluded.note,created=excluded.created""",
        (request_id,rating,(note or "")[:1200],time.time()))
        run=c.execute("SELECT * FROM runs WHERE request_id=?",(request_id,)).fetchone()
    return dict(run) if run else None

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
