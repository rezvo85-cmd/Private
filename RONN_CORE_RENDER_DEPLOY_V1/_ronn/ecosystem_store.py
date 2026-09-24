import base64
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from owner_auth import hash_token, new_recovery_code, new_session_token, verify_signed_session

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "ecosystem_v1.sqlite3"
VAULT_KEY_FILE = DATA / "vault.key"
BACKUPS = DATA / "backups"
BACKUPS.mkdir(parents=True, exist_ok=True)
MAX_BACKUPS = max(3, min(100, int(os.getenv("RONN_MAX_LOCAL_BACKUPS", "20") or "20")))
PLUGIN_DIR = BASE / "plugins"
PLUGIN_DIR.mkdir(parents=True, exist_ok=True)


def _db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS devices(
          owner TEXT NOT NULL, device_id TEXT NOT NULL, name TEXT, platform TEXT, app_version TEXT,
          trusted INTEGER DEFAULT 0, revoked INTEGER DEFAULT 0, push_token TEXT DEFAULT '',
          created REAL NOT NULL, last_seen REAL NOT NULL, PRIMARY KEY(owner,device_id));
        CREATE TABLE IF NOT EXISTS permissions(
          owner TEXT NOT NULL, device_id TEXT NOT NULL, permission TEXT NOT NULL, allowed INTEGER DEFAULT 0,
          updated REAL NOT NULL, PRIMARY KEY(owner,device_id,permission));
        CREATE TABLE IF NOT EXISTS owner_sessions(
          token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, client_id TEXT, device_id TEXT,
          created REAL NOT NULL, expires REAL NOT NULL, revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS recovery_codes(
          code_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL, used REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sync_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, resource_type TEXT NOT NULL,
          resource_id TEXT NOT NULL, op TEXT NOT NULL, payload_json TEXT NOT NULL, created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_sync_owner_seq ON sync_events(owner,seq);
        CREATE TABLE IF NOT EXISTS actions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, action_type TEXT NOT NULL,
          resource TEXT DEFAULT '', detail_json TEXT DEFAULT '{}', inverse_json TEXT DEFAULT '{}',
          reversible INTEGER DEFAULT 0, undone INTEGER DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS vault_items(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, ciphertext TEXT NOT NULL,
          created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS handoffs(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, source_device TEXT DEFAULT '', target_device TEXT DEFAULT '',
          kind TEXT DEFAULT 'context', payload_json TEXT NOT NULL, status TEXT DEFAULT 'pending',
          created REAL NOT NULL, claimed REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS clipboard(
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, device_id TEXT DEFAULT '', kind TEXT DEFAULT 'text',
          payload TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
          category TEXT DEFAULT 'general', read INTEGER DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS workflows(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, steps_json TEXT NOT NULL,
          enabled INTEGER DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS routines(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, workflow_id TEXT DEFAULT '', prompt TEXT DEFAULT '',
          interval_minutes INTEGER NOT NULL, enabled INTEGER DEFAULT 1, next_run REAL NOT NULL, last_run REAL DEFAULT 0,
          created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS shortcuts(
          owner TEXT NOT NULL, alias TEXT NOT NULL, prompt TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY(owner,alias));
        CREATE TABLE IF NOT EXISTS workspaces(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS collaborators(
          workspace_id TEXT NOT NULL, owner TEXT NOT NULL, subject TEXT NOT NULL, role TEXT NOT NULL,
          status TEXT DEFAULT 'invited', created REAL NOT NULL, PRIMARY KEY(workspace_id,subject));
        CREATE TABLE IF NOT EXISTS feature_flags(
          owner TEXT NOT NULL, flag TEXT NOT NULL, enabled INTEGER DEFAULT 0, updated REAL NOT NULL,
          PRIMARY KEY(owner,flag));
        CREATE TABLE IF NOT EXISTS credits(
          owner TEXT PRIMARY KEY, balance INTEGER NOT NULL, updated REAL NOT NULL);
        """
    )
    return c


def _id(prefix):
    return prefix + "_" + uuid.uuid4().hex[:22]


def _j(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _loads(v, default=None):
    try:
        return json.loads(v)
    except Exception:
        return {} if default is None else default


# ---------- devices / owner sessions ----------
def register_device(owner, device_id, name="", platform="", app_version="", trusted=False, push_token=""):
    device_id = (device_id or _id("dev"))[:120]
    now = time.time()
    with _db() as c:
        c.execute(
            """INSERT INTO devices(owner,device_id,name,platform,app_version,trusted,revoked,push_token,created,last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(owner,device_id) DO UPDATE SET
                 name=excluded.name, platform=excluded.platform, app_version=excluded.app_version,
                 trusted=CASE WHEN excluded.trusted=1 THEN 1 ELSE devices.trusted END,
                 push_token=CASE WHEN excluded.push_token<>'' THEN excluded.push_token ELSE devices.push_token END,
                 revoked=0, last_seen=excluded.last_seen""",
            (
                owner,
                device_id,
                (name or "RONN device")[:120],
                (platform or "")[:80],
                (app_version or "")[:80],
                1 if trusted else 0,
                0,
                (push_token or "")[:500],
                now,
                now,
            ),
        )
    return get_device(owner, device_id)


def get_device(owner, device_id):
    with _db() as c:
        r = c.execute("SELECT * FROM devices WHERE owner=? AND device_id=?", (owner, device_id)).fetchone()
    return dict(r) if r else None


def list_devices(owner):
    with _db() as c:
        rows = c.execute("SELECT * FROM devices WHERE owner=? ORDER BY revoked ASC,last_seen DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def revoke_device(owner, device_id):
    with _db() as c:
        cur = c.execute("UPDATE devices SET revoked=1,trusted=0 WHERE owner=? AND device_id=?", (owner, device_id))
        c.execute("UPDATE owner_sessions SET revoked=1 WHERE owner=? AND device_id=?", (owner, device_id))
    log_action(owner, "device.revoke", device_id, {"device_id": device_id})
    return cur.rowcount > 0


def set_permission(owner, device_id, permission, allowed):
    permission = "".join(ch for ch in (permission or "").lower() if ch.isalnum() or ch in "_-.")[:80]
    if not permission:
        return False
    with _db() as c:
        c.execute(
            """INSERT INTO permissions(owner,device_id,permission,allowed,updated) VALUES(?,?,?,?,?)
               ON CONFLICT(owner,device_id,permission) DO UPDATE SET allowed=excluded.allowed,updated=excluded.updated""",
            (owner, device_id, permission, 1 if allowed else 0, time.time()),
        )
    record_sync(owner, "permission", f"{device_id}:{permission}", "upsert", {"device_id": device_id, "permission": permission, "allowed": bool(allowed)})
    return True


def list_permissions(owner, device_id):
    with _db() as c:
        rows = c.execute("SELECT permission,allowed,updated FROM permissions WHERE owner=? AND device_id=? ORDER BY permission", (owner, device_id)).fetchall()
    return [{**dict(r), "allowed": bool(r["allowed"])} for r in rows]


def create_owner_session(owner, client_id="", device_id="", days=180):
    now = time.time()
    days = max(1, min(int(days), 365))
    exp = now + days * 86400
    token = new_session_token(owner, client_id, device_id, days)
    with _db() as c:
        c.execute(
            "INSERT INTO owner_sessions(token_hash,owner,client_id,device_id,created,expires,revoked) VALUES(?,?,?,?,?,?,0)",
            (hash_token(token), owner, (client_id or "")[:120], (device_id or "")[:120], now, exp),
        )
    return token, exp


def verify_owner_session(token, owner=None):
    if not token:
        return False

    signed = verify_signed_session(token, owner)
    with _db() as c:
        r = c.execute("SELECT * FROM owner_sessions WHERE token_hash=?", (hash_token(token),)).fetchone()

    # New signed sessions survive Render deploys even if the local SQLite file
    # is replaced. When the local record exists, still honor revocation.
    if signed:
        if r and (r["revoked"] or r["expires"] < time.time()):
            return False
        device_id = str(signed.get("d") or "")
        signed_owner = str(signed.get("o") or owner or "")
        if device_id:
            d = get_device(signed_owner, device_id)
            if d and d.get("revoked"):
                return False
        return True

    # Legacy opaque sessions remain valid until they expire.
    if not r or r["revoked"] or r["expires"] < time.time():
        return False
    if owner and r["owner"] != owner:
        return False
    if r["device_id"]:
        d = get_device(r["owner"], r["device_id"])
        if d and d.get("revoked"):
            return False
    return True


def revoke_owner_session(token):
    if not token:
        return False
    with _db() as c:
        cur = c.execute("UPDATE owner_sessions SET revoked=1 WHERE token_hash=?", (hash_token(token),))
    return cur.rowcount > 0


def generate_recovery_codes(owner, count=8):
    codes = [new_recovery_code() for _ in range(max(3, min(int(count), 12)))]
    now = time.time()
    with _db() as c:
        c.execute("DELETE FROM recovery_codes WHERE owner=?", (owner,))
        c.executemany(
            "INSERT INTO recovery_codes(code_hash,owner,created,used) VALUES(?,?,?,0)",
            [(hash_token(code), owner, now) for code in codes],
        )
    log_action(owner, "owner.recovery_codes.rotate", "owner", {"count": len(codes)})
    return codes


def use_recovery_code(owner, code):
    h = hash_token(code)
    with _db() as c:
        r = c.execute("SELECT used FROM recovery_codes WHERE owner=? AND code_hash=?", (owner, h)).fetchone()
        if not r or r["used"]:
            return False
        c.execute("UPDATE recovery_codes SET used=? WHERE owner=? AND code_hash=?", (time.time(), owner, h))
    return True


# ---------- sync / audit / undo ----------
def record_sync(owner, resource_type, resource_id, op, payload):
    with _db() as c:
        cur = c.execute(
            "INSERT INTO sync_events(owner,resource_type,resource_id,op,payload_json,created) VALUES(?,?,?,?,?,?)",
            (owner, resource_type, resource_id, op, _j(payload), time.time()),
        )
        return int(cur.lastrowid)


def pull_sync(owner, since=0, limit=500):
    with _db() as c:
        rows = c.execute(
            "SELECT * FROM sync_events WHERE owner=? AND seq>? ORDER BY seq ASC LIMIT ?",
            (owner, int(since), max(1, min(int(limit), 1000))),
        ).fetchall()
    events = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.pop("payload_json"), {})
        events.append(d)
    return {"events": events, "cursor": events[-1]["seq"] if events else int(since)}


def log_action(owner, action_type, resource="", detail=None, inverse=None):
    inv = inverse or {}
    with _db() as c:
        cur = c.execute(
            "INSERT INTO actions(owner,action_type,resource,detail_json,inverse_json,reversible,undone,created) VALUES(?,?,?,?,?,?,0,?)",
            (owner, action_type, (resource or "")[:220], _j(detail or {}), _j(inv), 1 if inv else 0, time.time()),
        )
        return int(cur.lastrowid)


def actions(owner, limit=100):
    with _db() as c:
        rows = c.execute("SELECT * FROM actions WHERE owner=? ORDER BY id DESC LIMIT ?", (owner, max(1, min(int(limit), 250)))).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = _loads(d.pop("detail_json"), {})
        d["inverse"] = _loads(d.pop("inverse_json"), {})
        d["reversible"] = bool(d["reversible"])
        d["undone"] = bool(d["undone"])
        out.append(d)
    return out


def action_by_id(owner, action_id):
    with _db() as c:
        r = c.execute("SELECT * FROM actions WHERE owner=? AND id=?", (owner, int(action_id))).fetchone()
    if not r:
        return None
    d = dict(r)
    d["detail"] = _loads(d.pop("detail_json"), {})
    d["inverse"] = _loads(d.pop("inverse_json"), {})
    return d


def mark_undone(owner, action_id):
    with _db() as c:
        cur = c.execute("UPDATE actions SET undone=1 WHERE owner=? AND id=? AND reversible=1 AND undone=0", (owner, int(action_id)))
    return cur.rowcount > 0


# ---------- encrypted vault ----------
def _derived_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(("RONN-VAULT-V1\0" + str(secret or "")).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _stable_vault_key():
    master = (os.getenv("RONN_VAULT_MASTER_KEY") or "").strip()
    if master:
        raw = master.encode("utf-8")
        try:
            Fernet(raw)
            return raw, "vault_master_key"
        except Exception:
            return _derived_fernet_key(master), "vault_master_secret"

    shared = (
        (os.getenv("RONN_SESSION_SIGNING_KEY") or "").strip()
        or (os.getenv("RONN_CORE_TOKEN") or "").strip()
    )
    if shared:
        return _derived_fernet_key(shared), "server_secret_derived"
    return None, ""


def _read_local_vault_key():
    if not VAULT_KEY_FILE.exists():
        return None
    try:
        key = VAULT_KEY_FILE.read_bytes().strip()
        Fernet(key)
        return key
    except Exception:
        return None


def _write_local_vault_key(key: bytes):
    VAULT_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_KEY_FILE.write_bytes(key)
    try:
        os.chmod(VAULT_KEY_FILE, 0o600)
    except Exception:
        pass


def _migrate_vault_ciphertexts(old_key: bytes, new_key: bytes) -> bool:
    if old_key == new_key:
        return True
    with _db() as c:
        rows = c.execute("SELECT id,ciphertext FROM vault_items").fetchall()
        converted = []
        try:
            old = Fernet(old_key)
            new = Fernet(new_key)
            for row in rows:
                plain = old.decrypt(row["ciphertext"].encode("ascii"))
                converted.append((new.encrypt(plain).decode("ascii"), row["id"]))
        except Exception:
            return False
        if converted:
            c.executemany("UPDATE vault_items SET ciphertext=? WHERE id=?", converted)
    return True


def vault_key_status():
    stable, source = _stable_vault_key()
    local = _read_local_vault_key()
    on_render = bool((os.getenv("RENDER") or "").strip() or (os.getenv("RENDER_SERVICE_ID") or "").strip())
    if stable:
        return {
            "available": True,
            "durable": True,
            "source": source,
            "legacy_local_key": bool(local and local != stable),
            "render_guarded": on_render,
        }
    if local:
        return {
            "available": True,
            "durable": not on_render,
            "source": "local_file",
            "legacy_local_key": False,
            "render_guarded": on_render,
        }
    return {
        "available": not on_render,
        "durable": False,
        "source": "local_generated" if not on_render else "unconfigured",
        "legacy_local_key": False,
        "render_guarded": on_render,
    }


def _vault_key():
    stable, _source = _stable_vault_key()
    local = _read_local_vault_key()

    if stable:
        if local and local != stable:
            # Local/offline installations may already have encrypted items.
            # Migrate them atomically before switching to the stable server key.
            if not _migrate_vault_ciphertexts(local, stable):
                return local
        _write_local_vault_key(stable)
        return stable

    if local:
        if (os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")):
            raise RuntimeError("Vault encryption requires a stable server key on Render.")
        return local

    if (os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")):
        raise RuntimeError(
            "Vault encryption is unavailable until RONN_VAULT_MASTER_KEY, "
            "RONN_SESSION_SIGNING_KEY, or RONN_CORE_TOKEN is configured."
        )

    key = Fernet.generate_key()
    _write_local_vault_key(key)
    return key


def vault_put(owner, title, text, item_id=None):
    item_id = item_id or _id("vault")
    now = time.time()
    cipher = Fernet(_vault_key()).encrypt((text or "").encode("utf-8")).decode("ascii")
    with _db() as c:
        c.execute(
            """INSERT INTO vault_items(id,owner,title,ciphertext,created,updated) VALUES(?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,ciphertext=excluded.ciphertext,updated=excluded.updated""",
            (item_id, owner, (title or "Secure note")[:180], cipher, now, now),
        )
    log_action(owner, "vault.write", item_id, {"title": title})
    return {"id": item_id, "title": title or "Secure note", "updated": now}


def vault_list(owner):
    with _db() as c:
        rows = c.execute("SELECT id,title,created,updated FROM vault_items WHERE owner=? ORDER BY updated DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def vault_get(owner, item_id):
    with _db() as c:
        r = c.execute("SELECT * FROM vault_items WHERE owner=? AND id=?", (owner, item_id)).fetchone()
    if not r:
        return None
    try:
        text = Fernet(_vault_key()).decrypt(r["ciphertext"].encode()).decode("utf-8")
    except Exception:
        return None
    return {"id": r["id"], "title": r["title"], "text": text, "created": r["created"], "updated": r["updated"]}


def vault_delete(owner, item_id):
    with _db() as c:
        cur = c.execute("DELETE FROM vault_items WHERE owner=? AND id=?", (owner, item_id))
    log_action(owner, "vault.delete", item_id, {})
    return cur.rowcount > 0


# ---------- handoff / clipboard / notifications ----------
def create_handoff(owner, source_device, kind, payload, target_device=""):
    hid = _id("handoff")
    now = time.time()
    with _db() as c:
        c.execute(
            "INSERT INTO handoffs(id,owner,source_device,target_device,kind,payload_json,status,created,claimed) VALUES(?,?,?,?,?,?,?, ?,0)",
            (hid, owner, source_device or "", target_device or "", kind or "context", _j(payload), "pending", now),
        )
    record_sync(owner, "handoff", hid, "create", {"kind": kind, "source_device": source_device, "target_device": target_device})
    return hid


def list_handoffs(owner, status="pending"):
    with _db() as c:
        rows = c.execute("SELECT * FROM handoffs WHERE owner=? AND status=? ORDER BY created DESC LIMIT 50", (owner, status)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.pop("payload_json"), {})
        out.append(d)
    return out


def claim_handoff(owner, handoff_id, device_id=""):
    with _db() as c:
        r = c.execute("SELECT * FROM handoffs WHERE owner=? AND id=? AND status='pending'", (owner, handoff_id)).fetchone()
        if not r:
            return None
        c.execute(
            "UPDATE handoffs SET status='claimed',target_device=CASE WHEN target_device='' THEN ? ELSE target_device END,claimed=? WHERE owner=? AND id=?",
            (device_id, time.time(), owner, handoff_id),
        )
    d = dict(r)
    d["payload"] = _loads(d.pop("payload_json"), {})
    return d


def clipboard_push(owner, device_id, payload, kind="text"):
    with _db() as c:
        cur = c.execute(
            "INSERT INTO clipboard(owner,device_id,kind,payload,created) VALUES(?,?,?,?,?)",
            (owner, device_id or "", kind or "text", (payload or "")[:200000], time.time()),
        )
        cid = int(cur.lastrowid)
    record_sync(owner, "clipboard", str(cid), "create", {"device_id": device_id, "kind": kind})
    return cid


def clipboard_latest(owner, after_id=0):
    with _db() as c:
        r = c.execute("SELECT * FROM clipboard WHERE owner=? AND id>? ORDER BY id DESC LIMIT 1", (owner, int(after_id))).fetchone()
    return dict(r) if r else None


def notification_add(owner, title, body, category="general"):
    with _db() as c:
        cur = c.execute(
            "INSERT INTO notifications(owner,title,body,category,read,created) VALUES(?,?,?,?,0,?)",
            (owner, (title or "RONN")[:180], (body or "")[:4000], category or "general", time.time()),
        )
        return int(cur.lastrowid)


def notifications(owner, unread_only=False, limit=100):
    with _db() as c:
        if unread_only:
            rows = c.execute("SELECT * FROM notifications WHERE owner=? AND read=0 ORDER BY id DESC LIMIT ?", (owner, int(limit))).fetchall()
        else:
            rows = c.execute("SELECT * FROM notifications WHERE owner=? ORDER BY id DESC LIMIT ?", (owner, int(limit))).fetchall()
    return [dict(r) for r in rows]


def notification_read(owner, nid):
    with _db() as c:
        cur = c.execute("UPDATE notifications SET read=1 WHERE owner=? AND id=?", (owner, int(nid)))
    return cur.rowcount > 0


# ---------- workflows / routines / shortcuts ----------
def workflow_save(owner, name, steps, workflow_id=None):
    wid = workflow_id or _id("wf")
    now = time.time()
    steps = list(steps or [])[:40]
    with _db() as c:
        c.execute(
            """INSERT INTO workflows(id,owner,name,steps_json,enabled,created,updated) VALUES(?,?,?,?,1,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,steps_json=excluded.steps_json,updated=excluded.updated""",
            (wid, owner, (name or "Workflow")[:160], _j(steps), now, now),
        )
    record_sync(owner, "workflow", wid, "upsert", {"name": name, "steps": steps})
    return wid


def workflows(owner):
    with _db() as c:
        rows = c.execute("SELECT * FROM workflows WHERE owner=? ORDER BY updated DESC", (owner,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["steps"] = _loads(d.pop("steps_json"), [])
        d["enabled"] = bool(d["enabled"])
        out.append(d)
    return out


def workflow_get(owner, workflow_id):
    with _db() as c:
        r = c.execute("SELECT * FROM workflows WHERE owner=? AND id=?", (owner, workflow_id)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["steps"] = _loads(d.pop("steps_json"), [])
    d["enabled"] = bool(d["enabled"])
    return d


def routine_save(owner, name, interval_minutes, prompt="", workflow_id="", routine_id=None):
    rid = routine_id or _id("routine")
    now = time.time()
    mins = max(60, int(interval_minutes or 60))
    with _db() as c:
        c.execute(
            """INSERT INTO routines(id,owner,name,workflow_id,prompt,interval_minutes,enabled,next_run,last_run,created,updated)
               VALUES(?,?,?,?,?,?,1,?,0,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,workflow_id=excluded.workflow_id,prompt=excluded.prompt,
                 interval_minutes=excluded.interval_minutes,enabled=1,next_run=excluded.next_run,updated=excluded.updated""",
            (rid, owner, (name or "Routine")[:160], workflow_id or "", (prompt or "")[:10000], mins, now + mins * 60, now, now),
        )
    return rid


def routines(owner):
    with _db() as c:
        rows = c.execute("SELECT * FROM routines WHERE owner=? ORDER BY updated DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def due_routines(now=None):
    now = now or time.time()
    with _db() as c:
        rows = c.execute("SELECT * FROM routines WHERE enabled=1 AND next_run<=? ORDER BY next_run ASC LIMIT 100", (now,)).fetchall()
    return [dict(r) for r in rows]


def mark_routine_run(rid):
    now = time.time()
    with _db() as c:
        r = c.execute("SELECT interval_minutes FROM routines WHERE id=?", (rid,)).fetchone()
        if not r:
            return False
        c.execute("UPDATE routines SET last_run=?,next_run=?,updated=? WHERE id=?", (now, now + int(r["interval_minutes"]) * 60, now, rid))
    return True


def shortcut_set(owner, alias, prompt):
    alias = (alias or "").strip().lower().lstrip("/")[:40]
    if not alias:
        return False
    now = time.time()
    with _db() as c:
        c.execute(
            """INSERT INTO shortcuts(owner,alias,prompt,created,updated) VALUES(?,?,?,?,?)
               ON CONFLICT(owner,alias) DO UPDATE SET prompt=excluded.prompt,updated=excluded.updated""",
            (owner, alias, (prompt or "")[:10000], now, now),
        )
    return True


def shortcuts(owner):
    with _db() as c:
        rows = c.execute("SELECT alias,prompt,updated FROM shortcuts WHERE owner=? ORDER BY alias", (owner,)).fetchall()
    return [dict(r) for r in rows]


def expand_shortcut(owner, text):
    s = (text or "").strip()
    if not s.startswith("/"):
        return text
    first, *rest = s.split(maxsplit=1)
    alias = first[1:].lower()
    with _db() as c:
        r = c.execute("SELECT prompt FROM shortcuts WHERE owner=? AND alias=?", (owner, alias)).fetchone()
    if not r:
        return text
    extra = rest[0] if rest else ""
    return (r["prompt"] + "\n\n" + extra).strip()


# ---------- workspaces / collaborators ----------
def workspace_create(owner, name):
    wid = _id("ws")
    now = time.time()
    with _db() as c:
        c.execute("INSERT INTO workspaces(id,owner,name,created,updated) VALUES(?,?,?,?,?)", (wid, owner, (name or "Workspace")[:160], now, now))
    record_sync(owner, "workspace", wid, "create", {"name": name})
    return wid


def workspaces(owner):
    with _db() as c:
        rows = c.execute("SELECT * FROM workspaces WHERE owner=? ORDER BY updated DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def collaborator_invite(owner, workspace_id, subject, role="viewer"):
    if role not in {"viewer", "editor"}:
        role = "viewer"
    with _db() as c:
        c.execute(
            "INSERT OR REPLACE INTO collaborators(workspace_id,owner,subject,role,status,created) VALUES(?,?,?,?,?,?)",
            (workspace_id, owner, (subject or "")[:240], role, "invited", time.time()),
        )
    return True


def collaborators(owner, workspace_id):
    with _db() as c:
        rows = c.execute("SELECT subject,role,status,created FROM collaborators WHERE owner=? AND workspace_id=?", (owner, workspace_id)).fetchall()
    return [dict(r) for r in rows]


# ---------- feature flags / credits ----------
DEFAULT_FLAGS = {
    "mobile_sync": True,
    "device_manager": True,
    "encrypted_vault": True,
    "handoff": True,
    "universal_clipboard": True,
    "notification_inbox": True,
    "workflow_builder": True,
    "scheduled_routines": True,
    "skills_plugins": True,
    "workspaces": True,
    "collaborators": False,
    "desktop_agent_experimental": False,
    "local_mobile_model": False,
    "native_widgets": False,
    "lock_screen_actions": False,
    "cloud_push_delivery": False,
}


def flags(owner):
    with _db() as c:
        rows = c.execute("SELECT flag,enabled FROM feature_flags WHERE owner=?", (owner,)).fetchall()
    d = dict(DEFAULT_FLAGS)
    d.update({r["flag"]: bool(r["enabled"]) for r in rows})
    return d


def set_flag(owner, flag, enabled):
    flag = "".join(ch for ch in (flag or "") if ch.isalnum() or ch in "_-.")[:100]
    if not flag:
        return False
    prev = flags(owner).get(flag, False)
    with _db() as c:
        c.execute(
            """INSERT INTO feature_flags(owner,flag,enabled,updated) VALUES(?,?,?,?)
               ON CONFLICT(owner,flag) DO UPDATE SET enabled=excluded.enabled,updated=excluded.updated""",
            (owner, flag, 1 if enabled else 0, time.time()),
        )
    log_action(owner, "feature_flag.set", flag, {"enabled": bool(enabled)}, {"type": "feature_flag", "flag": flag, "enabled": bool(prev)})
    record_sync(owner, "feature_flag", flag, "upsert", {"enabled": bool(enabled)})
    return True


def credits(owner, owner_unlimited=False):
    if owner_unlimited:
        return {"mode": "owner_unlimited", "balance": None, "unlimited": True}
    default = max(0, int(os.getenv("RONN_DEFAULT_CREDITS", "100")))
    with _db() as c:
        r = c.execute("SELECT balance FROM credits WHERE owner=?", (owner,)).fetchone()
        if not r:
            c.execute("INSERT INTO credits(owner,balance,updated) VALUES(?,?,?)", (owner, default, time.time()))
            bal = default
        else:
            bal = int(r["balance"])
    return {"mode": "credits", "balance": bal, "unlimited": False}


def consume_credit(owner, amount=1):
    amount = max(0, int(amount))
    default = max(0, int(os.getenv("RONN_DEFAULT_CREDITS", "100")))
    with _db() as c:
        r = c.execute("SELECT balance FROM credits WHERE owner=?", (owner,)).fetchone()
        bal = int(r["balance"]) if r else default
        if bal < amount:
            return False
        if r:
            c.execute("UPDATE credits SET balance=?,updated=? WHERE owner=?", (bal - amount, time.time(), owner))
        else:
            c.execute("INSERT INTO credits(owner,balance,updated) VALUES(?,?,?)", (owner, bal - amount, time.time()))
    return True


# ---------- backups / plugins / status ----------
def _backup_sqlite(source: Path, destination: Path):
    src = sqlite3.connect(str(source), timeout=10)
    dst = sqlite3.connect(str(destination), timeout=10)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def _prune_backups(limit=None):
    keep = MAX_BACKUPS if limit is None else max(1, min(int(limit), 100))
    folders = sorted(
        [x for x in BACKUPS.iterdir() if x.is_dir()],
        key=lambda x: x.name,
        reverse=True,
    )
    removed = []
    for folder in folders[keep:]:
        try:
            for child in folder.iterdir():
                if child.is_file():
                    child.unlink()
            folder.rmdir()
            removed.append(folder.name)
        except OSError:
            continue
    return removed


def backup_all(label="auto"):
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(label or "auto")).strip("-")[:40] or "auto"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = BACKUPS / f"{stamp}-{safe_label}-{uuid.uuid4().hex[:6]}"
    folder.mkdir(parents=True, exist_ok=False)

    copied = []
    errors = []
    seen = set()
    for p in list(DATA.glob("*.sqlite3")) + list(DATA.glob("*.db")):
        if p.name in seen or not p.is_file():
            continue
        seen.add(p.name)
        try:
            _backup_sqlite(p, folder / p.name)
            copied.append(p.name)
        except Exception as exc:
            errors.append({"file": p.name, "error": exc.__class__.__name__})

    meta = {
        "created": time.time(),
        "files": copied,
        "errors": errors,
        "consistent_sqlite_snapshot": True,
    }
    (folder / "backup.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    removed = _prune_backups()
    return {
        "folder": str(folder),
        "files": copied,
        "errors": errors,
        "created": meta["created"],
        "consistent_sqlite_snapshot": True,
        "retention_limit": MAX_BACKUPS,
        "pruned": removed,
    }


def list_backups(limit=20):
    limit = max(1, min(int(limit), 100))
    out = []
    for p in sorted([x for x in BACKUPS.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)[:limit]:
        try:
            d = json.loads((p / "backup.json").read_text(encoding="utf-8"))
            out.append({"name": p.name, **d})
        except Exception:
            pass
    return out


def plugin_manifests():
    out = []
    for p in sorted(PLUGIN_DIR.glob("*/manifest.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["path"] = str(p.parent)
            out.append(d)
        except Exception:
            pass
    return out


def status(owner, owner_unlimited=False):
    with _db() as c:
        dev = c.execute("SELECT COUNT(*) n FROM devices WHERE owner=? AND revoked=0", (owner,)).fetchone()["n"]
        unread = c.execute("SELECT COUNT(*) n FROM notifications WHERE owner=? AND read=0", (owner,)).fetchone()["n"]
        acts = c.execute("SELECT COUNT(*) n FROM actions WHERE owner=?", (owner,)).fetchone()["n"]
        sync = c.execute("SELECT COALESCE(MAX(seq),0) n FROM sync_events WHERE owner=?", (owner,)).fetchone()["n"]
    return {
        "devices": dev,
        "unread_notifications": unread,
        "actions": acts,
        "sync_cursor": sync,
        "flags": flags(owner),
        "credits": credits(owner, owner_unlimited),
        "vault_available": bool(vault_key_status().get("available")),
        "vault_key": vault_key_status(),
        "local_backup_retention": MAX_BACKUPS,
        "plugins": len(plugin_manifests()),
        "cloud_ready": True,
    }
