"""RONN R18 proactive/deployment monitoring while the Core is awake."""
from __future__ import annotations
import os, sqlite3, threading, time, uuid
from pathlib import Path
from r17_browser import fetch as browser_fetch

BASE=Path(__file__).resolve().parent
DB=BASE/"data"/"r18_monitor.db"
DB.parent.mkdir(exist_ok=True)
MAX_WATCHES_PER_OWNER=max(5,min(500,int(os.getenv("RONN_MONITOR_MAX_WATCHES_PER_OWNER","50") or "50")))
MAX_ALERTS_PER_OWNER=max(50,min(5000,int(os.getenv("RONN_MONITOR_MAX_ALERTS_PER_OWNER","500") or "500")))
_STOP=threading.Event(); _THREAD=None; _LOCK=threading.Lock()

def _db():
    c=sqlite3.connect(DB,check_same_thread=False);c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS watches(
      id TEXT PRIMARY KEY,owner TEXT,label TEXT,url TEXT,interval_s INTEGER,enabled INTEGER,
      last_ok INTEGER,last_status INTEGER,last_error TEXT,last_checked INTEGER,next_check INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS alerts(
      id TEXT PRIMARY KEY,watch_id TEXT,owner TEXT,message TEXT,created_at INTEGER,seen INTEGER DEFAULT 0)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_watches_owner ON watches(owner,enabled,next_check)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_alerts_owner_created ON alerts(owner,created_at DESC)")
    c.commit();return c

def add(owner,label,url,interval_s=900):
    owner=str(owner)[:120];url=str(url)[:1500]
    interval=max(300,min(int(interval_s),86400))
    with _db() as c:
        existing=c.execute(
            "SELECT * FROM watches WHERE owner=? AND url=? LIMIT 1",
            (owner,url),
        ).fetchone()
        if existing:
            return dict(existing)
        count=c.execute("SELECT COUNT(*) n FROM watches WHERE owner=?",(owner,)).fetchone()["n"]
        if int(count)>=MAX_WATCHES_PER_OWNER:
            raise ValueError("Monitor watch limit reached. Remove an old watch before adding another.")
        wid="watch_"+uuid.uuid4().hex[:16];now=int(time.time())
        c.execute("INSERT INTO watches VALUES(?,?,?,?,?,?,?,?,?,?,?)",
          (wid,owner,str(label or url)[:180],url,interval,1,None,None,"",0,now));c.commit()
    return get(wid)

def ensure(owner,label,url,interval_s=900):
    with _db() as c:
        r=c.execute("SELECT * FROM watches WHERE owner=? AND url=? LIMIT 1",(str(owner),str(url))).fetchone()
    if r:return dict(r)
    return add(owner,label,url,interval_s)

def get(wid):
    with _db() as c:r=c.execute("SELECT * FROM watches WHERE id=?",(str(wid),)).fetchone()
    return dict(r) if r else None

def list_watches(owner):
    with _db() as c:
        rows=c.execute(
            "SELECT * FROM watches WHERE owner=? ORDER BY label LIMIT ?",
            (str(owner),MAX_WATCHES_PER_OWNER),
        ).fetchall()
    return [dict(x) for x in rows]


def remove(owner,wid):
    with _db() as c:
        c.execute("DELETE FROM alerts WHERE owner=? AND watch_id=?",(str(owner),str(wid)))
        cur=c.execute("DELETE FROM watches WHERE owner=? AND id=?",(str(owner),str(wid)))
        c.commit()
    return cur.rowcount>0


def _alert(c,w,message):
    owner=str(w["owner"])
    c.execute(
        "INSERT INTO alerts VALUES(?,?,?,?,?,0)",
        ("alert_"+uuid.uuid4().hex[:16],w["id"],owner,message[:800],int(time.time())),
    )
    c.execute("""DELETE FROM alerts WHERE owner=? AND id NOT IN (
        SELECT id FROM alerts WHERE owner=? ORDER BY created_at DESC,rowid DESC LIMIT ?
    )""",(owner,owner,MAX_ALERTS_PER_OWNER))

def check(wid):
    w=get(wid)
    if not w:return {"ok":False,"error":"watch not found"}
    now=int(time.time()); ok=False; status=0; error=""
    try:
        page=browser_fetch(w["url"],timeout=10);status=int(page.get("status_code") or 0);ok=bool(page.get("ok"))
    except Exception as exc:
        error=str(exc)[:300]
    with _db() as c:
        prev=w.get("last_ok")
        if prev is not None and bool(prev)!=ok:
            _alert(c,w,(w["label"]+": recovered") if ok else (w["label"]+": check failed"))
        c.execute("""UPDATE watches SET last_ok=?,last_status=?,last_error=?,last_checked=?,next_check=?
                     WHERE id=?""",(1 if ok else 0,status,error,now,now+int(w["interval_s"]),wid));c.commit()
    return get(wid)

def alerts(owner,unseen_only=False,limit=40):
    q="SELECT * FROM alerts WHERE owner=?"+(" AND seen=0" if unseen_only else "")+" ORDER BY created_at DESC,rowid DESC LIMIT ?"
    with _db() as c:rows=c.execute(q,(str(owner),max(1,min(int(limit),100)))).fetchall()
    return [dict(x) for x in rows]

def mark_seen(owner):
    with _db() as c:c.execute("UPDATE alerts SET seen=1 WHERE owner=?",(str(owner),));c.commit()
    return True

def _loop():
    while not _STOP.wait(20):
        now=int(time.time())
        with _db() as c:rows=c.execute("SELECT id FROM watches WHERE enabled=1 AND next_check<=? LIMIT 10",(now,)).fetchall()
        for r in rows:
            try:check(r["id"])
            except Exception:pass

def start():
    global _THREAD
    with _LOCK:
        if _THREAD and _THREAD.is_alive():return status()
        _STOP.clear();_THREAD=threading.Thread(target=_loop,name="ronn-monitor",daemon=True);_THREAD.start()
    return status()

def status():
    with _db() as c:
        w=c.execute("SELECT COUNT(*) n FROM watches WHERE enabled=1").fetchone()["n"]
        a=c.execute("SELECT COUNT(*) n FROM alerts WHERE seen=0").fetchone()["n"]
    return {
        "running":bool(_THREAD and _THREAD.is_alive()),
        "active_watches":int(w),
        "unseen_alerts":int(a),
        "minimum_interval_s":300,
        "max_watches_per_owner":MAX_WATCHES_PER_OWNER,
        "max_alerts_per_owner":MAX_ALERTS_PER_OWNER,
    }
