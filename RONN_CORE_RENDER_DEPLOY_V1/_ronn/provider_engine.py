import sqlite3
import time
from pathlib import Path

BASE=Path(__file__).resolve().parent
DB=BASE/'data'/'provider_health.sqlite3'
DB.parent.mkdir(parents=True,exist_ok=True)

def _db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS provider_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, model TEXT,
      ok INTEGER, status_code INTEGER DEFAULT 0, latency REAL DEFAULT 0,
      error_class TEXT DEFAULT '', created REAL
    );
    CREATE INDEX IF NOT EXISTS idx_provider_recent ON provider_events(provider,model,created DESC);
    ''')
    return c

def record(provider,model,ok,status_code=0,latency=0,error_class=''):
    with _db() as c:
        c.execute('INSERT INTO provider_events(provider,model,ok,status_code,latency,error_class,created) VALUES(?,?,?,?,?,?,?)',
                  ((provider or '')[:40],(model or '')[:200],1 if ok else 0,int(status_code or 0),float(latency or 0),(error_class or '')[:100],time.time()))
        # Bound history.
        c.execute('DELETE FROM provider_events WHERE id NOT IN (SELECT id FROM provider_events ORDER BY id DESC LIMIT 2500)')

def recent_health(provider=None,model=None,window=20):
    where=[];args=[]
    if provider:where.append('provider=?');args.append(provider)
    if model:where.append('model=?');args.append(model)
    sql='SELECT * FROM provider_events'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY created DESC LIMIT ?'
    args.append(int(window))
    with _db() as c:
        rows=c.execute(sql,args).fetchall()
    if not rows:return {'samples':0,'success_rate':None,'avg_latency':None,'consecutive_failures':0}
    ok=[int(r['ok']) for r in rows]
    successes=[float(r['latency']) for r in rows if r['ok'] and r['latency']]
    streak=0
    for r in rows:
        if r['ok']:break
        streak+=1
    return {'samples':len(rows),'success_rate':round(sum(ok)/len(ok),3),'avg_latency':round(sum(successes)/len(successes),3) if successes else None,'consecutive_failures':streak,'last_status':rows[0]['status_code'],'last_error_class':rows[0]['error_class']}

def model_penalty(model):
    h=recent_health(model=model,window=12)
    if not h['samples']:return 0
    penalty=h['consecutive_failures']*2
    if h['success_rate'] is not None and h['success_rate']<.5:penalty+=4
    elif h['success_rate'] is not None and h['success_rate']<.75:penalty+=2
    return penalty

def rank_models(models):
    indexed=list(enumerate(models))
    indexed.sort(key=lambda x:(model_penalty(x[1]),x[0]))
    return [m for _,m in indexed]

def summary():
    with _db() as c:
        rows=c.execute('SELECT DISTINCT provider,model FROM provider_events ORDER BY provider,model').fetchall()
    return [{'provider':r['provider'],'model':r['model'],**recent_health(r['provider'],r['model'])} for r in rows]
