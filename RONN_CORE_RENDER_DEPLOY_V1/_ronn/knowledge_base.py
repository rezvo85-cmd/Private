import re
import sqlite3
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / 'data' / 'knowledge.sqlite3'
DB.parent.mkdir(parents=True, exist_ok=True)
STOP = {'the','and','for','that','this','with','from','are','was','were','you','your','have','has','had','not','but','can','will','into','about','what','when','where','who','why','how'}


def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS kb_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner TEXT, project_id TEXT, kind TEXT, title TEXT, content TEXT,
      fingerprint TEXT, created REAL, updated REAL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_unique ON kb_items(owner,project_id,fingerprint);
    CREATE INDEX IF NOT EXISTS idx_kb_owner_project ON kb_items(owner,project_id,updated DESC);
    ''')
    return c


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9_.'-]+", (text or '').lower()) if len(w) > 2 and w not in STOP}


def _fingerprint(kind, title, content):
    import hashlib
    return hashlib.sha256((kind+'\n'+title+'\n'+content).encode('utf-8', errors='ignore')).hexdigest()


def ingest(owner, project_id, kind, title, content):
    content = str(content or '').strip()
    title = str(title or '').strip()[:220]
    if not content:
        return None
    content = content[:60000]
    fp = _fingerprint(kind, title, content)
    now = time.time()
    with _db() as c:
        row = c.execute('SELECT id FROM kb_items WHERE owner=? AND project_id=? AND fingerprint=?',(owner,project_id,fp)).fetchone()
        if row:
            c.execute('UPDATE kb_items SET updated=? WHERE id=?',(now,row['id']))
            return int(row['id'])
        cur = c.execute('INSERT INTO kb_items(owner,project_id,kind,title,content,fingerprint,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                        (owner,project_id,kind[:40],title,content,fp,now,now))
        # Bound per owner to avoid unbounded local growth.
        c.execute('DELETE FROM kb_items WHERE owner=? AND id NOT IN (SELECT id FROM kb_items WHERE owner=? ORDER BY updated DESC LIMIT 1200)',(owner,owner))
        return int(cur.lastrowid)


def ingest_files(owner, project_id, files):
    ids=[]
    for f in list(files or [])[:24]:
        name=getattr(f,'name','file') or 'file'
        content=getattr(f,'content','') or ''
        if content.strip():
            ids.append(ingest(owner,project_id,'file',name,content))
    return [x for x in ids if x]


def search(owner, query, project_id=None, limit=8, cross_project=False):
    q=_tokens(query)
    if not q:
        return []
    with _db() as c:
        if project_id and not cross_project:
            rows=c.execute('SELECT * FROM kb_items WHERE owner=? AND project_id=? ORDER BY updated DESC LIMIT 400',(owner,project_id)).fetchall()
        else:
            rows=c.execute('SELECT * FROM kb_items WHERE owner=? ORDER BY updated DESC LIMIT 600',(owner,)).fetchall()
    scored=[]
    now=time.time()
    for r in rows:
        text=(r['title'] or '')+' '+(r['content'] or '')
        overlap=len(q & _tokens(text))
        if not overlap: continue
        age=max(0.0,(now-float(r['updated'] or now))/86400.0)
        rec=max(0.0,1.2-min(1.2,age/45.0))
        kind_bonus=.6 if r['kind'] in {'decision','failure','file','research'} else .2
        score=overlap*3+rec+kind_bonus
        scored.append((score,dict(r)))
    scored.sort(key=lambda x:x[0],reverse=True)
    out=[]
    for score,row in scored[:max(1,min(int(limit),20))]:
        row['score']=round(score,2)
        row['content']=row['content'][:5000]
        out.append(row)
    return out


def context_block(owner, project_id, query, limit=6):
    rows=search(owner,query,project_id,limit=limit,cross_project=False)
    if not rows:return ''
    return '\n'.join(f"- [{r['kind']}] {r['title']}: {r['content'][:900]}" for r in rows)


def stats(owner=None):
    with _db() as c:
        if owner:
            total=c.execute('SELECT COUNT(*) n FROM kb_items WHERE owner=?',(owner,)).fetchone()['n']
            projects=c.execute('SELECT COUNT(DISTINCT project_id) n FROM kb_items WHERE owner=?',(owner,)).fetchone()['n']
        else:
            total=c.execute('SELECT COUNT(*) n FROM kb_items').fetchone()['n']
            projects=c.execute('SELECT COUNT(DISTINCT project_id) n FROM kb_items').fetchone()['n']
    return {'items':total,'projects':projects}
