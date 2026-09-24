import sqlite3
import time
import json
import os
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/'data'/'tasks.sqlite3'
DB.parent.mkdir(parents=True,exist_ok=True)
MAX_TASKS_PER_OWNER=max(100,min(5000,int(os.getenv("RONN_MAX_TASKS_PER_OWNER","600") or "600")))
MAX_CHECKPOINTS_PER_TASK=max(20,min(1000,int(os.getenv("RONN_MAX_CHECKPOINTS_PER_TASK","200") or "200")))

def _db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS tasks(
      task_id TEXT PRIMARY KEY, owner TEXT, project_id TEXT, signature TEXT,
      prompt TEXT, profile TEXT, difficulty INTEGER, status TEXT,
      plan_json TEXT, created REAL, updated REAL
    );
    CREATE TABLE IF NOT EXISTS checkpoints(
      id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, phase TEXT,
      status TEXT, detail TEXT DEFAULT '', created REAL
    );
    CREATE INDEX IF NOT EXISTS idx_task_owner_updated ON tasks(owner,updated DESC);
    CREATE INDEX IF NOT EXISTS idx_checkpoint_task ON checkpoints(task_id,id);
    ''')
    return c


def _prune_owner(c,owner):
    rows=c.execute(
        """SELECT task_id FROM tasks
           WHERE owner=? AND status!='running'
           ORDER BY updated DESC""",
        (owner,),
    ).fetchall()
    stale=[r["task_id"] for r in rows[MAX_TASKS_PER_OWNER:]]
    if not stale:
        return 0
    c.executemany("DELETE FROM checkpoints WHERE task_id=?",[(task_id,) for task_id in stale])
    c.executemany("DELETE FROM tasks WHERE task_id=?",[(task_id,) for task_id in stale])
    return len(stale)


def _prune_checkpoints(c,task_id):
    c.execute(
        """DELETE FROM checkpoints WHERE task_id=? AND id NOT IN (
             SELECT id FROM checkpoints WHERE task_id=? ORDER BY id DESC LIMIT ?
           )""",
        (task_id,task_id,MAX_CHECKPOINTS_PER_TASK),
    )

def start_task(task_id,owner,project_id,prompt,profile,difficulty,signature,plan):
    now=time.time()
    with _db() as c:
        c.execute('''INSERT OR REPLACE INTO tasks(task_id,owner,project_id,signature,prompt,profile,difficulty,status,plan_json,created,updated)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                  (task_id,owner,project_id,signature,(prompt or '')[:16000],profile,int(difficulty),'running',json.dumps(plan,ensure_ascii=False),now,now))
        _prune_owner(c,owner)

def checkpoint(task_id,phase,status='complete',detail=''):
    now=time.time()
    with _db() as c:
        c.execute('INSERT INTO checkpoints(task_id,phase,status,detail,created) VALUES(?,?,?,?,?)',
                  (task_id,(phase or '')[:100],(status or '')[:40],(detail or '')[:4000],now))
        _prune_checkpoints(c,task_id)
        c.execute('UPDATE tasks SET updated=? WHERE task_id=?',(now,task_id))

def finish_task(task_id,status='complete'):
    with _db() as c:
        row=c.execute('SELECT owner FROM tasks WHERE task_id=?',(task_id,)).fetchone()
        c.execute('UPDATE tasks SET status=?,updated=? WHERE task_id=?',((status or 'complete')[:40],time.time(),task_id))
        if row:
            _prune_owner(c,row["owner"])

def get_task(task_id):
    with _db() as c:
        task=c.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone()
        cps=c.execute('SELECT phase,status,detail,created FROM checkpoints WHERE task_id=? ORDER BY id',(task_id,)).fetchall()
    if not task:return None
    out=dict(task)
    try:out['plan']=json.loads(out.pop('plan_json') or '{}')
    except Exception:out['plan']={}
    out['checkpoints']=[dict(x) for x in cps]
    return out

def recent_tasks(owner,limit=20):
    limit=max(1,min(int(limit),100))
    with _db() as c:
        rows=c.execute('SELECT task_id,project_id,signature,prompt,profile,difficulty,status,created,updated FROM tasks WHERE owner=? ORDER BY updated DESC LIMIT ?',
                       (owner,limit)).fetchall()
    return [dict(x) for x in rows]

def stats():
    with _db() as c:
        total=c.execute('SELECT COUNT(*) n FROM tasks').fetchone()['n']
        complete=c.execute("SELECT COUNT(*) n FROM tasks WHERE status='complete'").fetchone()['n']
        failed=c.execute("SELECT COUNT(*) n FROM tasks WHERE status='failed'").fetchone()['n']
        cps=c.execute('SELECT COUNT(*) n FROM checkpoints').fetchone()['n']
    return {
        'tasks':total,
        'completed':complete,
        'failed':failed,
        'checkpoints':cps,
        'max_tasks_per_owner':MAX_TASKS_PER_OWNER,
        'max_checkpoints_per_task':MAX_CHECKPOINTS_PER_TASK,
    }


def latest_incomplete(owner, project_id=None):
    with _db() as c:
        if project_id:
            row=c.execute("SELECT task_id FROM tasks WHERE owner=? AND project_id=? AND status IN ('running','cancelled','failed') ORDER BY updated DESC LIMIT 1",(owner,project_id)).fetchone()
        else:
            row=c.execute("SELECT task_id FROM tasks WHERE owner=? AND status IN ('running','cancelled','failed') ORDER BY updated DESC LIMIT 1",(owner,)).fetchone()
    return get_task(row['task_id']) if row else None
