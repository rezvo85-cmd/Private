import json
import sqlite3
import time
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/'data'/'task_queue.sqlite3'
DB.parent.mkdir(parents=True,exist_ok=True)


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
    ''')
    return c


def add(owner,project_id,title,prompt,priority=50):
    now=time.time(); priority=max(0,min(100,int(priority)))
    with _db() as c:
        cur=c.execute('INSERT INTO queue(owner,project_id,title,prompt,priority,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                      (owner,project_id,(title or 'Task')[:160],(prompt or '')[:16000],priority,'queued',now,now))
        return int(cur.lastrowid)


def list_items(owner,status=None,limit=50):
    with _db() as c:
        if status:
            rows=c.execute('SELECT * FROM queue WHERE owner=? AND status=? ORDER BY priority DESC,created ASC LIMIT ?',(owner,status,int(limit))).fetchall()
        else:
            rows=c.execute('SELECT * FROM queue WHERE owner=? ORDER BY CASE status WHEN "running" THEN 0 WHEN "queued" THEN 1 ELSE 2 END,priority DESC,updated DESC LIMIT ?',(owner,int(limit))).fetchall()
    return [dict(r) for r in rows]


def update(owner,item_id,status):
    if status not in {'queued','running','complete','cancelled','failed'}:return False
    with _db() as c:
        cur=c.execute('UPDATE queue SET status=?,updated=? WHERE owner=? AND id=?',(status,time.time(),owner,int(item_id)))
        return cur.rowcount>0


def stats(owner):
    with _db() as c:
        rows=c.execute('SELECT status,COUNT(*) n FROM queue WHERE owner=? GROUP BY status',(owner,)).fetchall()
    d={r['status']:r['n'] for r in rows}
    return {'total':sum(d.values()),**d}
