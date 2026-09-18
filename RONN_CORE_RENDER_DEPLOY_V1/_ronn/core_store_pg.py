from __future__ import annotations

import json
import os
import time
import uuid

import psycopg
from psycopg.rows import dict_row

URL=(os.getenv("DATABASE_URL") or "").strip()

def enabled():
    return bool(URL)

def _db():
    if not URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(URL,row_factory=dict_row)

def _id(prefix):
    return prefix+"_"+uuid.uuid4().hex[:20]

def init():
    if not URL:return False
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS core_projects(
              owner TEXT NOT NULL, project_id TEXT NOT NULL, name TEXT NOT NULL,
              description TEXT DEFAULT '', created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
              PRIMARY KEY(owner,project_id)
            );
            CREATE TABLE IF NOT EXISTS core_conversations(
              owner TEXT NOT NULL, conversation_id TEXT NOT NULL, project_id TEXT DEFAULT 'default',
              title TEXT DEFAULT 'New chat', created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
              PRIMARY KEY(owner,conversation_id)
            );
            CREATE TABLE IF NOT EXISTS core_messages(
              id BIGSERIAL PRIMARY KEY, owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
              role TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT DEFAULT '{}',
              created DOUBLE PRECISION NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_core_messages_conv_pg ON core_messages(owner,conversation_id,id);
            CREATE TABLE IF NOT EXISTS core_settings(
              owner TEXT PRIMARY KEY, settings_json TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL
            );
            """)
        c.commit()
    return True

def ensure_default_project(owner):
    init(); now=time.time()
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO core_projects(owner,project_id,name,description,created,updated)
                           VALUES(%s,'default','Default','',%s,%s)
                           ON CONFLICT(owner,project_id) DO NOTHING""",(owner,now,now))
        c.commit()
    return "default"

def list_projects(owner):
    ensure_default_project(owner)
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM core_projects WHERE owner=%s ORDER BY updated DESC",(owner,))
            return list(cur.fetchall())

def create_project(owner,name,description=""):
    ensure_default_project(owner); pid=_id("prj"); now=time.time()
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO core_projects(owner,project_id,name,description,created,updated)
                           VALUES(%s,%s,%s,%s,%s,%s)""",
                        (owner,pid,(name or "Untitled project").strip()[:120],(description or "")[:2000],now,now))
        c.commit()
    return get_project(owner,pid)

def get_project(owner,project_id):
    ensure_default_project(owner)
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM core_projects WHERE owner=%s AND project_id=%s",(owner,project_id))
            return cur.fetchone()

def update_project(owner,project_id,name=None,description=None):
    p=get_project(owner,project_id)
    if not p:return None
    current_name=p["name"] if name is None else (name or "Untitled project").strip()[:120]
    current_desc=p["description"] if description is None else (description or "")[:2000]
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""UPDATE core_projects SET name=%s,description=%s,updated=%s
                           WHERE owner=%s AND project_id=%s""",
                        (current_name,current_desc,time.time(),owner,project_id))
        c.commit()
    return get_project(owner,project_id)

def delete_project(owner,project_id):
    if project_id=="default":return False
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM core_projects WHERE owner=%s AND project_id=%s",(owner,project_id))
            deleted=cur.rowcount>0
            cur.execute("UPDATE core_conversations SET project_id='default' WHERE owner=%s AND project_id=%s",(owner,project_id))
        c.commit()
    return deleted

def create_conversation(owner,project_id="default",title="New chat"):
    ensure_default_project(owner)
    if not get_project(owner,project_id):project_id="default"
    cid=_id("conv");now=time.time()
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO core_conversations(owner,conversation_id,project_id,title,created,updated)
                           VALUES(%s,%s,%s,%s,%s,%s)""",(owner,cid,project_id,(title or "New chat")[:160],now,now))
        c.commit()
    return get_conversation(owner,cid,False)

def ensure_conversation(owner,conversation_id=None,project_id="default",title="New chat"):
    if conversation_id:
        found=get_conversation(owner,conversation_id,False)
        if found:return found
    return create_conversation(owner,project_id,title)

def list_conversations(owner,project_id=None,limit=100):
    with _db() as c:
        with c.cursor() as cur:
            if project_id:
                cur.execute("""SELECT * FROM core_conversations WHERE owner=%s AND project_id=%s
                               ORDER BY updated DESC LIMIT %s""",(owner,project_id,int(limit)))
            else:
                cur.execute("""SELECT * FROM core_conversations WHERE owner=%s
                               ORDER BY updated DESC LIMIT %s""",(owner,int(limit)))
            return list(cur.fetchall())

def get_conversation(owner,conversation_id,include_messages=True):
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM core_conversations WHERE owner=%s AND conversation_id=%s",(owner,conversation_id))
            row=cur.fetchone()
            if not row:return None
            out=dict(row)
            if include_messages:
                cur.execute("""SELECT id,role,content,metadata_json,created FROM core_messages
                               WHERE owner=%s AND conversation_id=%s ORDER BY id ASC""",(owner,conversation_id))
                msgs=[]
                for m in cur.fetchall():
                    d=dict(m)
                    try:d["metadata"]=json.loads(d.pop("metadata_json") or "{}")
                    except Exception:d["metadata"]={};d.pop("metadata_json",None)
                    msgs.append(d)
                out["messages"]=msgs
            return out

def add_message(owner,conversation_id,role,content,metadata=None):
    content=(content or "").strip()
    if not content:return None
    now=time.time()
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO core_messages(owner,conversation_id,role,content,metadata_json,created)
                           VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (owner,conversation_id,role[:20],content[:100000],json.dumps(metadata or {},ensure_ascii=False),now))
            mid=cur.fetchone()["id"]
            cur.execute("UPDATE core_conversations SET updated=%s WHERE owner=%s AND conversation_id=%s",(now,owner,conversation_id))
            if role=="user":
                cur.execute("SELECT title FROM core_conversations WHERE owner=%s AND conversation_id=%s",(owner,conversation_id))
                row=cur.fetchone()
                if row and (row["title"] or "")=="New chat":
                    title=" ".join(content.split())[:72] or "New chat"
                    cur.execute("UPDATE core_conversations SET title=%s WHERE owner=%s AND conversation_id=%s",(title,owner,conversation_id))
        c.commit()
    return int(mid)

def delete_conversation(owner,conversation_id):
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM core_messages WHERE owner=%s AND conversation_id=%s",(owner,conversation_id))
            cur.execute("DELETE FROM core_conversations WHERE owner=%s AND conversation_id=%s",(owner,conversation_id))
            ok=cur.rowcount>0
        c.commit()
    return ok

DEFAULT_SETTINGS={"response_style":"auto","reasoning_mode":"auto","agent_mode":True}

def get_settings(owner):
    init()
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT settings_json FROM core_settings WHERE owner=%s",(owner,))
            row=cur.fetchone()
    if not row:return dict(DEFAULT_SETTINGS)
    try:data=json.loads(row["settings_json"] or "{}")
    except Exception:data={}
    return {**DEFAULT_SETTINGS,**{k:v for k,v in data.items() if k in DEFAULT_SETTINGS}}

def update_settings(owner,patch):
    current=get_settings(owner)
    for k,v in (patch or {}).items():
        if k in DEFAULT_SETTINGS:current[k]=v
    current["agent_mode"]=bool(current.get("agent_mode",True))
    if current.get("response_style")=="short":current["response_style"]="concise"
    if current.get("response_style") not in {"auto","concise","balanced","detailed"}:current["response_style"]="auto"
    if current.get("reasoning_mode") not in {"auto","fast","deep","apex"}:current["reasoning_mode"]="auto"
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO core_settings(owner,settings_json,updated) VALUES(%s,%s,%s)
                           ON CONFLICT(owner) DO UPDATE SET settings_json=EXCLUDED.settings_json,updated=EXCLUDED.updated""",
                        (owner,json.dumps(current),time.time()))
        c.commit()
    return current

def stats(owner):
    ensure_default_project(owner)
    with _db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) n FROM core_projects WHERE owner=%s",(owner,));p=cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) n FROM core_conversations WHERE owner=%s",(owner,));conv=cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) n FROM core_messages WHERE owner=%s",(owner,));msg=cur.fetchone()["n"]
    return {"projects":p,"conversations":conv,"messages":msg,"backend":"postgres"}
