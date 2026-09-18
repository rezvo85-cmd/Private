"""RONN R15 durable cloud-brain mirror.

Keeps the existing SQLite-based subsystems compatible while optionally mirroring
RONN's local data databases into PostgreSQL. On a fresh deploy the cloud copy can
restore those databases before normal use. No provider/API secrets are mirrored.
"""
from __future__ import annotations
import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

_DATABASE_URL=(os.getenv("DATABASE_URL") or "").strip()
_SYNC_SECONDS=max(20,int(os.getenv("RONN_CLOUD_SYNC_SECONDS","45") or "45"))
_STOP=threading.Event()
_THREAD=None
_LAST={}
_LOCK=threading.Lock()

try:
    import psycopg
except Exception:
    psycopg=None

_ALLOWED={".db",".sqlite",".sqlite3",".json"}
_BLOCK=("token","secret","key","credential","vault")

def configured():
    return bool(_DATABASE_URL)

def driver_ready():
    return psycopg is not None

def _connect():
    if not configured():
        raise RuntimeError("DATABASE_URL is not configured.")
    if psycopg is None:
        raise RuntimeError("psycopg is not installed.")
    return psycopg.connect(_DATABASE_URL,autocommit=True)

def _init():
    if not configured() or psycopg is None:
        return False
    with _connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS ronn_cloud_files(
            name TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            payload BYTEA NOT NULL,
            updated_at BIGINT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS ronn_cloud_events(
            id BIGSERIAL PRIMARY KEY,
            owner TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )""")
    return True

def _safe_file(path: Path):
    n=path.name.lower()
    return path.is_file() and path.suffix.lower() in _ALLOWED and not any(x in n for x in _BLOCK)

def _sha(data: bytes):
    return hashlib.sha256(data).hexdigest()

def _stable_bytes(path: Path):
    """Return a consistent snapshot of a live SQLite DB, including WAL state."""
    if path.suffix.lower() not in {".db",".sqlite",".sqlite3"}:
        return path.read_bytes()
    fd,tmp=tempfile.mkstemp(prefix="ronn-cloud-",suffix=path.suffix)
    os.close(fd)
    try:
        src=sqlite3.connect(str(path),timeout=3)
        dst=sqlite3.connect(tmp)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close();src.close()
        return Path(tmp).read_bytes()
    finally:
        try: os.unlink(tmp)
        except OSError: pass

def restore_directory(data_dir):
    """Restore durable database/json files before RONN starts using them."""
    root=Path(data_dir)
    if not _init():
        return {"configured":configured(),"restored":0,"durable":False}
    root.mkdir(parents=True,exist_ok=True)
    restored=0
    with _connect() as c:
        rows=c.execute("SELECT name,sha256,payload,updated_at FROM ronn_cloud_files").fetchall()
    for name,sha,payload,updated in rows:
        name=Path(str(name)).name
        dest=root/name
        data=bytes(payload)
        if _sha(data)!=sha:
            continue
        # Cloud copy is authoritative on deploy. Use atomic replacement.
        tmp=dest.with_suffix(dest.suffix+".cloudtmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        _LAST[name]=sha
        restored+=1
    return {"configured":True,"restored":restored,"durable":True}

def snapshot_directory(data_dir):
    root=Path(data_dir)
    if not _init():
        return {"configured":configured(),"uploaded":0,"durable":False}
    uploaded=0
    for path in root.iterdir() if root.exists() else []:
        if not _safe_file(path):
            continue
        try:
            data=_stable_bytes(path)
        except (OSError,sqlite3.Error):
            continue
        # Skip unexpectedly huge local artifacts.
        if len(data)>25*1024*1024:
            continue
        sha=_sha(data)
        if _LAST.get(path.name)==sha:
            continue
        with _connect() as c:
            c.execute("""INSERT INTO ronn_cloud_files(name,sha256,payload,updated_at)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT(name) DO UPDATE SET
                  sha256=EXCLUDED.sha256,payload=EXCLUDED.payload,updated_at=EXCLUDED.updated_at""",
                (path.name,sha,data,int(time.time())))
        _LAST[path.name]=sha
        uploaded+=1
    return {"configured":True,"uploaded":uploaded,"durable":True}

def record_event(owner,kind,payload):
    if not _init():
        return False
    text=str(payload or "")[:12000]
    with _connect() as c:
        c.execute("INSERT INTO ronn_cloud_events(owner,kind,payload,created_at) VALUES(%s,%s,%s,%s)",
                  (str(owner or "default")[:120],str(kind or "event")[:80],text,int(time.time())))
    return True

def _loop(data_dir):
    while not _STOP.wait(_SYNC_SECONDS):
        try:
            snapshot_directory(data_dir)
        except Exception:
            pass

def start_sync(data_dir):
    global _THREAD
    if not configured() or not driver_ready():
        return status()
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return status()
        _STOP.clear()
        _THREAD=threading.Thread(target=_loop,args=(str(data_dir),),name="ronn-cloud-sync",daemon=True)
        _THREAD.start()
    return status()

def stop_sync():
    _STOP.set()

def status():
    ok=False; error=""
    if configured() and driver_ready():
        try:
            ok=_init()
        except Exception as exc:
            error=str(exc)[:180]
    return {
        "configured":configured(),
        "driver_ready":driver_ready(),
        "durable":bool(ok),
        "sync_seconds":_SYNC_SECONDS,
        "thread_alive":bool(_THREAD and _THREAD.is_alive()),
        "error":error,
    }
