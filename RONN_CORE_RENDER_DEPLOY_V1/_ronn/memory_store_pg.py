from __future__ import annotations

import os
import re
import time
import psycopg
from psycopg.rows import dict_row

URL=(os.getenv("DATABASE_URL") or "").strip()

def enabled():
    return bool(URL)

def _db():
    if not URL:raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(URL,row_factory=dict_row)

def init():
    if not URL:return False
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS ronn_memories(
              id BIGSERIAL PRIMARY KEY, text TEXT NOT NULL, created_at BIGINT NOT NULL,
              owner TEXT NOT NULL DEFAULT 'legacy', confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
              source TEXT NOT NULL DEFAULT 'user', updated_at BIGINT NOT NULL DEFAULT 0,
              category TEXT NOT NULL DEFAULT 'general', pinned INTEGER NOT NULL DEFAULT 0,
              use_count INTEGER NOT NULL DEFAULT 0, last_used BIGINT NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ronn_mem_owner ON ronn_memories(owner,updated_at DESC);
            CREATE TABLE IF NOT EXISTS ronn_history(
              id BIGSERIAL PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL,
              created_at BIGINT NOT NULL, owner TEXT NOT NULL DEFAULT 'legacy'
            );
            """)
        c.commit()
    return True

def save_message(owner,role,content):
    init();content=(content or "").strip()
    if not content:return
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO ronn_history(role,content,created_at,owner) VALUES(%s,%s,%s,%s)",
                        (role,content[:30000],int(time.time()),owner))
        c.commit()

def add_memory(owner,text,confidence=0.9,source="user",category="general"):
    init();text=re.sub(r"\s+"," ",text or "").strip()
    if not text:return False
    now=int(time.time());confidence=max(0.1,min(1.0,float(confidence)))
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT id,confidence FROM ronn_memories WHERE owner=%s AND lower(text)=lower(%s)",(owner,text))
            row=cur.fetchone()
            if row:
                cur.execute("""UPDATE ronn_memories SET updated_at=%s,confidence=GREATEST(confidence,%s),
                               source=%s,category=%s WHERE id=%s""",
                            (now,confidence,source[:40],category[:30],row["id"]))
            else:
                cur.execute("""INSERT INTO ronn_memories(text,created_at,owner,confidence,source,updated_at,category,pinned,use_count,last_used)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,0,0,0)""",
                            (text[:1200],now,owner,confidence,source[:40],now,category[:30]))
        c.commit()
    return True

def list_memories(owner):
    init()
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""SELECT id,text,created_at,updated_at,confidence,source,category,pinned,use_count,last_used
                           FROM ronn_memories WHERE owner=%s ORDER BY pinned DESC,updated_at DESC,id DESC LIMIT 100""",(owner,))
            return list(cur.fetchall())

def delete_memory(owner,memory_id):
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM ronn_memories WHERE owner=%s AND id=%s",(owner,memory_id));ok=cur.rowcount>0
        c.commit()
    return ok

def forget_matching(owner,query):
    q=(query or "").strip().lower()
    if not q:return 0
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT id,text FROM ronn_memories WHERE owner=%s",(owner,))
            ids=[r["id"] for r in cur.fetchall() if q in r["text"].lower()]
            if ids:cur.execute("DELETE FROM ronn_memories WHERE owner=%s AND id = ANY(%s)",(owner,ids))
        c.commit()
    return len(ids)

def update_memory(owner,memory_id,pinned=None,confidence=None,category=None):
    row=next((x for x in list_memories(owner) if int(x["id"])==int(memory_id)),None)
    if not row:return False
    new_p=int(bool(pinned)) if pinned is not None else int(row["pinned"])
    new_c=max(0.1,min(1.0,float(confidence))) if confidence is not None else float(row["confidence"])
    new_cat=(category or row["category"] or "general")[:30]
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""UPDATE ronn_memories SET pinned=%s,confidence=%s,category=%s,updated_at=%s
                           WHERE owner=%s AND id=%s""",
                        (new_p,new_c,new_cat,int(time.time()),owner,memory_id))
        c.commit()
    return True

def mark_used(owner,ids):
    if not ids:return
    now=int(time.time())
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""UPDATE ronn_memories SET use_count=use_count+1,last_used=%s
                           WHERE owner=%s AND id = ANY(%s)""",(now,owner,list(ids)))
        c.commit()

def status():
    return {"configured":bool(URL),"backend":"postgres" if URL else "sqlite-fallback"}
