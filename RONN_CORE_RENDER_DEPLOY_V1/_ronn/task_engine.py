import sqlite3
import time
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/'data'/'tasks.sqlite3'
DB.parent.mkdir(parents=True,exist_ok=True)

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

def start_task(task_id,owner,project_id,prompt,profile,difficulty,signature,plan):
    now=time.time()
    with _db() as c:
        c.execute('''INSERT OR REPLACE INTO tasks(task_id,owner,project_id,signature,prompt,profile,difficulty,status,plan_json,created,updated)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                  (task_id,owner,project_id,signature,(prompt or '')[:16000],profile,int(difficulty),'running',json.dumps(plan,ensure_ascii=False),now,now))

def checkpoint(task_id,phase,status='complete',detail=''):
    now=time.time()
    with _db() as c:
        c.execute('INSERT INTO checkpoints(task_id,phase,status,detail,created) VALUES(?,?,?,?,?)',
                  (task_id,(phase or '')[:100],(status or '')[:40],(detail or '')[:4000],now))
        c.execute('UPDATE tasks SET updated=? WHERE task_id=?',(now,task_id))

def finish_task(task_id,status='complete'):
    with _db() as c:
        c.execute('UPDATE tasks SET status=?,updated=? WHERE task_id=?',((status or 'complete')[:40],time.time(),task_id))

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
    with _db() as c:
        rows=c.execute('SELECT task_id,project_id,signature,prompt,profile,difficulty,status,created,updated FROM tasks WHERE owner=? ORDER BY updated DESC LIMIT ?',
                       (owner,int(limit))).fetchall()
    return [dict(x) for x in rows]

def stats():
    with _db() as c:
        total=c.execute('SELECT COUNT(*) n FROM tasks').fetchone()['n']
        complete=c.execute("SELECT COUNT(*) n FROM tasks WHERE status='complete'").fetchone()['n']
        failed=c.execute("SELECT COUNT(*) n FROM tasks WHERE status='failed'").fetchone()['n']
        cps=c.execute('SELECT COUNT(*) n FROM checkpoints').fetchone()['n']
    return {'tasks':total,'completed':complete,'failed':failed,'checkpoints':cps}


def latest_incomplete(owner, project_id=None):
    with _db() as c:
        if project_id:
            row=c.execute("SELECT task_id FROM tasks WHERE owner=? AND project_id=? AND status IN ('running','cancelled','failed') ORDER BY updated DESC LIMIT 1",(owner,project_id)).fetchone()
        else:
            row=c.execute("SELECT task_id FROM tasks WHERE owner=? AND status IN ('running','cancelled','failed') ORDER BY updated DESC LIMIT 1",(owner,)).fetchone()
    return get_task(row['task_id']) if row else None
