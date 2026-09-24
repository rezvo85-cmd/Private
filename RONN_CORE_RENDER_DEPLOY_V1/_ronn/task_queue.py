import json
import os
import sqlite3
import time
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/'data'/'task_queue.sqlite3'
DB.parent.mkdir(parents=True,exist_ok=True)
TASK_TERMINAL_TTL_SECONDS=max(86400,min(365*86400,int(os.getenv("RONN_TASK_TERMINAL_TTL_SECONDS",str(180*86400)) or str(180*86400))))
MAX_TERMINAL_TASKS_PER_OWNER=max(200,min(10000,int(os.getenv("RONN_TASK_MAX_TERMINAL_PER_OWNER","2000") or "2000")))


def _db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS queue(
      id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, project_id TEXT,
      title TEXT, prompt TEXT, priority INTEGER DEFAULT 50, status TEXT DEFAULT 'queued',
      created REAL, updated REAL
    );
    CREATE INDEX IF NOT EXISTS idx_queue_owner ON queue(owner,status,priority DESC,created ASC);
    CREATE INDEX IF NOT EXISTS idx_queue_owner_updated ON queue(owner,updated DESC);
    ''')
    return c


def _prune_terminal(c,owner,now=None):
    now=time.time() if now is None else float(now)
    owner=str(owner)
    cutoff=now-TASK_TERMINAL_TTL_SECONDS
    c.execute(
        "DELETE FROM queue WHERE owner=? AND status IN ('complete','cancelled','failed') AND updated<?",
        (owner,cutoff),
    )
    c.execute("""DELETE FROM queue WHERE owner=? AND status IN ('complete','cancelled','failed')
                 AND id NOT IN (
                    SELECT id FROM queue
                    WHERE owner=? AND status IN ('complete','cancelled','failed')
                    ORDER BY updated DESC,id DESC LIMIT ?
                 )""",(owner,owner,MAX_TERMINAL_TASKS_PER_OWNER))


def add(owner,project_id,title,prompt,priority=50):
    now=time.time(); priority=max(0,min(100,int(priority))); owner=str(owner)
    with _db() as c:
        _prune_terminal(c,owner,now)
        cur=c.execute('INSERT INTO queue(owner,project_id,title,prompt,priority,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                      (owner,project_id,(title or 'Task')[:160],(prompt or '')[:16000],priority,'queued',now,now))
        return int(cur.lastrowid)


def list_items(owner,status=None,limit=50):
    owner=str(owner);limit=max(1,min(int(limit),100))
    with _db() as c:
        _prune_terminal(c,owner)
        if status:
            rows=c.execute('SELECT * FROM queue WHERE owner=? AND status=? ORDER BY priority DESC,created ASC LIMIT ?',(owner,status,limit)).fetchall()
        else:
            rows=c.execute('SELECT * FROM queue WHERE owner=? ORDER BY CASE status WHEN "running" THEN 0 WHEN "queued" THEN 1 ELSE 2 END,priority DESC,updated DESC LIMIT ?',(owner,limit)).fetchall()
    return [dict(r) for r in rows]


def update(owner,item_id,status):
    if status not in {'queued','running','complete','cancelled','failed'}:return False
    owner=str(owner);now=time.time()
    with _db() as c:
        cur=c.execute('UPDATE queue SET status=?,updated=? WHERE owner=? AND id=?',(status,now,owner,int(item_id)))
        if status in {'complete','cancelled','failed'}:
            _prune_terminal(c,owner,now)
        return cur.rowcount>0


def stats(owner):
    owner=str(owner)
    with _db() as c:
        _prune_terminal(c,owner)
        rows=c.execute('SELECT status,COUNT(*) n FROM queue WHERE owner=? GROUP BY status',(owner,)).fetchall()
    d={r['status']:r['n'] for r in rows}
    return {'total':sum(d.values()),**d}
