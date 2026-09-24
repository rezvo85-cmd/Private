"""RONN R17 long-running task engine with durable checkpoints."""
from __future__ import annotations
import json, os, sqlite3, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r17_jobs.db"
DB.parent.mkdir(exist_ok=True)
POOL=ThreadPoolExecutor(max_workers=3,thread_name_prefix="ronn-job")
_LOCK=threading.Lock()
JOB_TERMINAL_TTL_SECONDS=max(86400,min(365*86400,int(os.getenv("RONN_JOB_TERMINAL_TTL_SECONDS",str(90*86400)) or str(90*86400))))
MAX_TERMINAL_JOBS_PER_OWNER=max(100,min(5000,int(os.getenv("RONN_JOB_MAX_TERMINAL_PER_OWNER","1000") or "1000")))

def _db():
    c=sqlite3.connect(DB,check_same_thread=False); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS jobs(
      id TEXT PRIMARY KEY, owner TEXT, kind TEXT, payload TEXT, status TEXT,
      progress INTEGER, result TEXT, error TEXT, created_at INTEGER, updated_at INTEGER)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_r17_jobs_owner_updated ON jobs(owner,updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_r17_jobs_kind_status ON jobs(kind,status,updated_at DESC)")
    c.commit(); return c


def _prune_terminal(c,owner,now=None):
    now=int(time.time() if now is None else now)
    owner=str(owner)
    cutoff=now-JOB_TERMINAL_TTL_SECONDS
    c.execute(
        "DELETE FROM jobs WHERE owner=? AND status IN ('completed','failed','cancelled') AND updated_at<?",
        (owner,cutoff),
    )
    c.execute("""DELETE FROM jobs WHERE owner=? AND status IN ('completed','failed','cancelled')
                 AND id NOT IN (
                    SELECT id FROM jobs
                    WHERE owner=? AND status IN ('completed','failed','cancelled')
                    ORDER BY updated_at DESC,id DESC LIMIT ?
                 )""",(owner,owner,MAX_TERMINAL_JOBS_PER_OWNER))

def _pack(x):
    try:return json.dumps(x,ensure_ascii=False)[:200000]
    except Exception:return json.dumps({"text":str(x)[:100000]})

def _submit_existing(jid,payload,runner):
    def work():
        update(jid,status="running",progress=5,error="")
        try:
            result=runner(payload,lambda p:update(jid,progress=max(5,min(int(p),95))))
            update(jid,status="completed",progress=100,result=result,error="")
        except Exception as exc:
            update(jid,status="failed",progress=100,error=str(exc)[:1200])
    POOL.submit(work)

def create(owner,kind,payload,runner):
    jid="job_"+uuid.uuid4().hex[:18]; now=int(time.time());owner=str(owner)[:120]
    with _db() as c:
        _prune_terminal(c,owner,now)
        c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
          (jid,owner,str(kind)[:80],_pack(payload),"queued",0,"","",now,now)); c.commit()
    _submit_existing(jid,payload,runner)
    return get(jid)

def update(jid,status=None,progress=None,result=None,error=None):
    fields=[]; args=[]
    if status is not None:fields.append("status=?");args.append(str(status))
    if progress is not None:fields.append("progress=?");args.append(max(0,min(int(progress),100)))
    if result is not None:fields.append("result=?");args.append(_pack(result))
    if error is not None:fields.append("error=?");args.append(str(error)[:5000])
    fields.append("updated_at=?");args.append(int(time.time()));args.append(str(jid))
    with _db() as c:
        c.execute("UPDATE jobs SET "+",".join(fields)+" WHERE id=?",args)
        if status in {"completed","failed","cancelled"}:
            row=c.execute("SELECT owner FROM jobs WHERE id=?",(str(jid),)).fetchone()
            if row:_prune_terminal(c,row["owner"])
        c.commit()
    return get(jid)

def get(jid):
    with _db() as c:r=c.execute("SELECT * FROM jobs WHERE id=?",(str(jid),)).fetchone()
    if not r:return None
    d=dict(r)
    for k in ("payload","result"):
        try:d[k]=json.loads(d[k]) if d[k] else None
        except Exception:pass
    return d

def list_jobs(owner,limit=40):
    owner=str(owner);limit=max(1,min(int(limit),100))
    with _db() as c:
        _prune_terminal(c,owner)
        rows=c.execute("SELECT id FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT ?",(owner,limit)).fetchall()
    return [get(r["id"]) for r in rows]

def stats(owner=None):
    with _db() as c:
        if owner:
            owner=str(owner);_prune_terminal(c,owner)
            rows=c.execute("SELECT status,COUNT(*) n FROM jobs WHERE owner=? GROUP BY status",(owner,)).fetchall()
        else:
            rows=c.execute("SELECT status,COUNT(*) n FROM jobs GROUP BY status").fetchall()
    return {r["status"]:int(r["n"]) for r in rows}


def resume(jid,runner):
    job=get(jid)
    if not job:return None
    if job.get("status") in {"running","queued"}:
        return job
    if job.get("status")=="completed":
        return job
    update(jid,status="queued",progress=0,error="")
    _submit_existing(jid,job.get("payload") or {},runner)
    return get(jid)

def recover_kind(kind,runner):
    """Resume queued/running jobs after an app restart for a known job kind."""
    with _db() as c:
        rows=c.execute("SELECT id FROM jobs WHERE kind=? AND status IN ('queued','running','interrupted')",(str(kind),)).fetchall()
        ids=[r["id"] for r in rows]
        for jid in ids:
            c.execute("UPDATE jobs SET status='interrupted',updated_at=? WHERE id=?",(int(time.time()),jid))
        c.commit()
    resumed=[]
    for jid in ids:
        job=get(jid)
        if job:
            update(jid,status="queued",progress=0,error="")
            _submit_existing(jid,job.get("payload") or {},runner)
            resumed.append(jid)
    return resumed

def mark_unknown_running_interrupted():
    with _db() as c:
        cur=c.execute("UPDATE jobs SET status='interrupted',updated_at=? WHERE status='running'",(int(time.time()),))
        c.commit()
    return cur.rowcount
