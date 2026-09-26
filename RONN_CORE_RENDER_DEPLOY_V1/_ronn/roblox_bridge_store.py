"""Persistent owner-scoped queue for the local RONN <-> Roblox Studio MCP bridge.

The cloud RONN service never connects inbound to a user's PC. A local bridge pairs
with a short-lived code, receives a long random token, then polls this durable
SQLite queue over outbound HTTPS. Only SHA-256 hashes of pairing codes/tokens are
stored.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import string
import threading
import time
import uuid
from pathlib import Path
from typing import Any

VERSION = "RONN-ROBLOX-BRIDGE-STORE-2"
PAIR_TTL_SECONDS = 600
BRIDGE_ONLINE_SECONDS = 25
DEFAULT_LEASE_SECONDS = 75
MAX_JOB_ATTEMPTS = 3
MAX_JSON_BYTES = 2 * 1024 * 1024
_PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_BRIDGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,120}$")


def _now() -> int:
    return int(time.time())


def _digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _json_dump(value: Any, *, limit: int = MAX_JSON_BYTES) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > limit:
        raise ValueError("JSON payload is too large.")
    return raw


def _json_load(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _safe_bridge_id(value: str) -> str:
    value = str(value or "").strip()
    if not _BRIDGE_ID_RE.fullmatch(value):
        raise ValueError("Invalid bridge id.")
    return value


def _safe_label(value: str, default: str = "RONN Roblox Bridge") -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return (value or default)[:120]


class RobloxBridgeStore:
    def __init__(self, path: str | os.PathLike | None = None):
        if path is None:
            base = Path(__file__).resolve().parent / "data"
            base.mkdir(parents=True, exist_ok=True)
            path = os.getenv("RONN_ROBLOX_BRIDGE_DB", str(base / "roblox_bridge.db"))
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialized = False
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS pair_codes(
                        code_hash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        used_at INTEGER
                    );
                    CREATE INDEX IF NOT EXISTS idx_pair_owner
                        ON pair_codes(owner, expires_at);

                    CREATE TABLE IF NOT EXISTS bridges(
                        token_hash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        bridge_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        last_seen INTEGER NOT NULL,
                        revoked_at INTEGER,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        UNIQUE(owner, bridge_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_bridge_owner
                        ON bridges(owner, last_seen);

                    CREATE TABLE IF NOT EXISTS owner_state(
                        owner TEXT PRIMARY KEY,
                        selected_bridge_id TEXT,
                        selected_studio_id TEXT,
                        updated_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS jobs(
                        job_id TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        bridge_id TEXT,
                        kind TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        available_at INTEGER NOT NULL,
                        claimed_at INTEGER,
                        claimed_bridge_id TEXT,
                        lease_until INTEGER,
                        completed_at INTEGER,
                        result_json TEXT,
                        error TEXT,
                        retry_safe INTEGER NOT NULL DEFAULT 1,
                        claim_token TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_jobs_pull
                        ON jobs(owner, status, available_at, created_at);
                    CREATE INDEX IF NOT EXISTS idx_jobs_owner
                        ON jobs(owner, created_at);
                    """
                )
                # Existing local/test databases may predate lease-generation fields.
                cols={row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
                if "retry_safe" not in cols:
                    conn.execute("ALTER TABLE jobs ADD COLUMN retry_safe INTEGER NOT NULL DEFAULT 1")
                if "claim_token" not in cols:
                    conn.execute("ALTER TABLE jobs ADD COLUMN claim_token TEXT")
            self._initialized = True

    def start_pairing(self, owner: str) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("Owner is required.")
        code = "".join(secrets.choice(_PAIR_ALPHABET) for _ in range(12))
        now = _now()
        expires = now + PAIR_TTL_SECONDS
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM pair_codes WHERE owner=? AND (used_at IS NULL OR expires_at<?)",
                (owner, now),
            )
            conn.execute(
                "INSERT INTO pair_codes(code_hash,owner,created_at,expires_at,used_at) VALUES(?,?,?,?,NULL)",
                (_digest(code), owner, now, expires),
            )
            conn.commit()
        return {"pair_code": code, "expires_at": expires, "expires_in": PAIR_TTL_SECONDS}

    def pair_bridge(self, pair_code: str, bridge_id: str, name: str = "", metadata=None) -> dict[str, Any]:
        bridge_id = _safe_bridge_id(bridge_id)
        code_hash = _digest(str(pair_code or "").strip().upper())
        now = _now()
        token = secrets.token_urlsafe(32)
        token_hash = _digest(token)
        metadata_json = _json_dump(metadata or {}, limit=256 * 1024)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner,expires_at,used_at FROM pair_codes WHERE code_hash=?",
                (code_hash,),
            ).fetchone()
            if not row or row["used_at"] is not None or int(row["expires_at"]) < now:
                conn.rollback()
                raise ValueError("Pairing code is invalid or expired.")
            owner = str(row["owner"])
            conn.execute(
                "UPDATE pair_codes SET used_at=? WHERE code_hash=?",
                (now, code_hash),
            )
            # Re-pairing the same local install intentionally invalidates its old token.
            conn.execute(
                "DELETE FROM bridges WHERE owner=? AND bridge_id=?",
                (owner, bridge_id),
            )
            conn.execute(
                """INSERT INTO bridges(
                    token_hash,owner,bridge_id,name,created_at,last_seen,revoked_at,metadata_json
                ) VALUES(?,?,?,?,?,?,NULL,?)""",
                (token_hash, owner, bridge_id, _safe_label(name), now, now, metadata_json),
            )
            conn.execute(
                """INSERT INTO owner_state(owner,selected_bridge_id,selected_studio_id,updated_at)
                   VALUES(?,?,NULL,?)
                   ON CONFLICT(owner) DO UPDATE SET
                     selected_bridge_id=excluded.selected_bridge_id,
                     selected_studio_id=NULL,
                     updated_at=excluded.updated_at""",
                (owner, bridge_id, now),
            )
            conn.commit()
        return {"owner": owner, "bridge_id": bridge_id, "token": token, "paired_at": now}

    def authenticate(self, token: str) -> dict[str, Any] | None:
        token = str(token or "").strip()
        if len(token) < 20:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """SELECT owner,bridge_id,name,created_at,last_seen,metadata_json
                   FROM bridges WHERE token_hash=? AND revoked_at IS NULL""",
                (_digest(token),),
            ).fetchone()
        if not row:
            return None
        return {
            "owner": row["owner"],
            "bridge_id": row["bridge_id"],
            "name": row["name"],
            "created_at": int(row["created_at"]),
            "last_seen": int(row["last_seen"]),
            "metadata": _json_load(row["metadata_json"], {}),
        }

    def heartbeat(self, token: str, metadata: dict[str, Any]) -> dict[str, Any]:
        auth = self.authenticate(token)
        if not auth:
            raise PermissionError("Bridge token is invalid or revoked.")
        now = _now()
        payload = dict(metadata or {})
        payload["bridge_version"] = str(payload.get("bridge_version") or "")[:80]
        payload["studios"] = list(payload.get("studios") or [])[:24]
        payload["tools"] = list(payload.get("tools") or [])[:80]
        metadata_json = _json_dump(payload, limit=768 * 1024)
        with self._connect() as conn:
            conn.execute(
                """UPDATE bridges SET last_seen=?,metadata_json=?
                   WHERE owner=? AND bridge_id=? AND revoked_at IS NULL""",
                (now, metadata_json, auth["owner"], auth["bridge_id"]),
            )
        auth.update({"last_seen": now, "metadata": payload})
        return auth

    def status(self, owner: str) -> dict[str, Any]:
        owner = str(owner or "")
        now = _now()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT bridge_id,name,created_at,last_seen,metadata_json
                   FROM bridges
                   WHERE owner=? AND revoked_at IS NULL
                   ORDER BY last_seen DESC""",
                (owner,),
            ).fetchall()
            state = conn.execute(
                "SELECT selected_bridge_id,selected_studio_id FROM owner_state WHERE owner=?",
                (owner,),
            ).fetchone()
        bridges = []
        for row in rows:
            metadata = _json_load(row["metadata_json"], {})
            bridges.append({
                "bridge_id": row["bridge_id"],
                "name": row["name"],
                "created_at": int(row["created_at"]),
                "last_seen": int(row["last_seen"]),
                "online": now - int(row["last_seen"]) <= BRIDGE_ONLINE_SECONDS,
                "studios": list(metadata.get("studios") or [])[:24],
                "tools": list(metadata.get("tools") or [])[:80],
                "platform": metadata.get("platform"),
                "bridge_version": metadata.get("bridge_version"),
                "mcp_connected": bool(metadata.get("mcp_connected")),
                "last_error": str(metadata.get("last_error") or "")[:300],
            })
        selected_bridge = str(state["selected_bridge_id"]) if state and state["selected_bridge_id"] else None
        selected_studio = str(state["selected_studio_id"]) if state and state["selected_studio_id"] else None
        return {
            "version": VERSION,
            "online": any(x["online"] and x["mcp_connected"] for x in bridges),
            "bridges": bridges,
            "selected_bridge_id": selected_bridge,
            "selected_studio_id": selected_studio,
        }

    def select_studio(self, owner: str, bridge_id: str, studio_id: str) -> dict[str, Any]:
        bridge_id = _safe_bridge_id(bridge_id)
        studio_id = str(studio_id or "").strip()
        if not studio_id or len(studio_id) > 240:
            raise ValueError("Invalid Studio id.")
        status = self.status(owner)
        bridge = next((x for x in status["bridges"] if x["bridge_id"] == bridge_id and x["online"]), None)
        if not bridge:
            raise ValueError("That RONN Roblox bridge is not online.")
        ids = {str(x.get("studio_id") or x.get("id") or "") for x in bridge.get("studios") or [] if isinstance(x, dict)}
        if studio_id not in ids:
            raise ValueError("That Roblox Studio window is no longer connected.")
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO owner_state(owner,selected_bridge_id,selected_studio_id,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(owner) DO UPDATE SET
                     selected_bridge_id=excluded.selected_bridge_id,
                     selected_studio_id=excluded.selected_studio_id,
                     updated_at=excluded.updated_at""",
                (owner, bridge_id, studio_id, now),
            )
        return {"bridge_id": bridge_id, "studio_id": studio_id, "selected": True}

    def enqueue(
        self,
        owner: str,
        kind: str,
        payload: dict[str, Any],
        *,
        bridge_id: str | None = None,
        retry_safe: bool = True,
    ) -> dict[str, Any]:
        owner = str(owner or "").strip()
        kind = re.sub(r"[^a-z0-9_.-]", "", str(kind or "").lower())[:64]
        if not owner or not kind:
            raise ValueError("Owner and job kind are required.")
        if bridge_id:
            bridge_id = _safe_bridge_id(bridge_id)
        raw = _json_dump(payload or {})
        job_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO jobs(
                    job_id,owner,bridge_id,kind,payload_json,status,attempts,
                    created_at,available_at,retry_safe,claim_token
                ) VALUES(?,?,?,?,?,'queued',0,?,?,?,NULL)""",
                (job_id, owner, bridge_id, kind, raw, now, now, 1 if retry_safe else 0),
            )
        return {"job_id": job_id, "status": "queued", "created_at": now}

    def _requeue_expired(self, conn, now: int):
        rows = conn.execute(
            """SELECT job_id,attempts,retry_safe,claim_token FROM jobs
               WHERE status='claimed' AND lease_until IS NOT NULL AND lease_until<?""",
            (now,),
        ).fetchall()
        for row in rows:
            # Read-only/idempotent jobs can safely be retried with a fresh claim
            # generation. Mutating Studio calls never auto-replay after an
            # ambiguous disconnect because the first execution may already have
            # changed the place even if its result never reached Core.
            if not bool(row["retry_safe"]):
                conn.execute(
                    """UPDATE jobs SET status='uncertain',completed_at=?,error=?,
                       lease_until=NULL
                       WHERE job_id=? AND status='claimed' AND claim_token=?""",
                    (
                        now,
                        "Mutation delivery became uncertain after the bridge lease expired; inspect Studio state before any further edit.",
                        row["job_id"],
                        row["claim_token"],
                    ),
                )
            elif int(row["attempts"]) >= MAX_JOB_ATTEMPTS:
                conn.execute(
                    """UPDATE jobs SET status='failed',completed_at=?,error=?,
                       claimed_bridge_id=NULL,lease_until=NULL,claim_token=NULL
                       WHERE job_id=?""",
                    (now, "Bridge lease expired too many times.", row["job_id"]),
                )
            else:
                conn.execute(
                    """UPDATE jobs SET status='queued',available_at=?,
                       claimed_at=NULL,claimed_bridge_id=NULL,lease_until=NULL,
                       claim_token=NULL
                       WHERE job_id=?""",
                    (now + 1, row["job_id"]),
                )

    def pull(self, token: str, *, limit: int = 1, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[dict[str, Any]]:
        auth = self.authenticate(token)
        if not auth:
            raise PermissionError("Bridge token is invalid or revoked.")
        limit = max(1, min(int(limit or 1), 4))
        lease_seconds = max(20, min(int(lease_seconds or DEFAULT_LEASE_SECONDS), 300))
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._requeue_expired(conn, now)
            rows = conn.execute(
                """SELECT job_id,kind,payload_json,attempts,created_at
                   FROM jobs
                   WHERE owner=? AND status='queued' AND available_at<=?
                     AND (bridge_id IS NULL OR bridge_id=?)
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (auth["owner"], now, auth["bridge_id"], limit),
            ).fetchall()
            out = []
            for row in rows:
                lease_until = now + lease_seconds
                claim_token = secrets.token_urlsafe(24)
                conn.execute(
                    """UPDATE jobs SET status='claimed',claimed_at=?,claimed_bridge_id=?,
                       lease_until=?,attempts=attempts+1,claim_token=?
                       WHERE job_id=? AND status='queued'""",
                    (now, auth["bridge_id"], lease_until, claim_token, row["job_id"]),
                )
                out.append({
                    "job_id": row["job_id"],
                    "kind": row["kind"],
                    "payload": _json_load(row["payload_json"], {}),
                    "attempt": int(row["attempts"]) + 1,
                    "created_at": int(row["created_at"]),
                    "lease_until": lease_until,
                    "claim_token": claim_token,
                })
            conn.commit()
        return out

    def complete(
        self,
        token: str,
        job_id: str,
        *,
        claim_token: str,
        result=None,
        error: str = "",
    ) -> dict[str, Any]:
        auth = self.authenticate(token)
        if not auth:
            raise PermissionError("Bridge token is invalid or revoked.")
        job_id = str(job_id or "").strip()
        now = _now()
        result_json = _json_dump(result or {}, limit=MAX_JSON_BYTES)
        error = re.sub(r"\s+", " ", str(error or "")).strip()[:4000]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT owner,status,claimed_bridge_id,claim_token,retry_safe
                   FROM jobs WHERE job_id=?""",
                (job_id,),
            ).fetchone()
            if not row or row["owner"] != auth["owner"]:
                conn.rollback()
                raise ValueError("Job was not found.")
            if row["status"] in {"completed", "failed"}:
                conn.rollback()
                return self.get_job(auth["owner"], job_id) or {"job_id": job_id, "status": row["status"]}
            supplied_claim=str(claim_token or "").strip()
            current_claim=str(row["claim_token"] or "")
            if (
                not supplied_claim
                or not current_claim
                or not secrets.compare_digest(supplied_claim,current_claim)
                or row["claimed_bridge_id"] != auth["bridge_id"]
            ):
                conn.rollback()
                raise PermissionError("This bridge completion is stale or does not own the current job claim.")
            if row["status"] not in {"claimed","uncertain"}:
                conn.rollback()
                raise PermissionError("This job is no longer accepting results for that claim.")
            # A late result for an unsafe mutation is allowed only while its exact
            # claim token is still current. Unsafe jobs are never handed to a
            # second executor, so this turns known evidence into a terminal result
            # without risking duplicate execution.
            status = "failed" if error else "completed"
            conn.execute(
                """UPDATE jobs SET status=?,completed_at=?,result_json=?,error=?,
                   lease_until=NULL WHERE job_id=? AND claim_token=?""",
                (status, now, result_json, error, job_id, current_claim),
            )
            conn.commit()
        return self.get_job(auth["owner"], job_id) or {"job_id": job_id, "status": status}

    def get_job(self, owner: str, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT job_id,bridge_id,kind,status,attempts,created_at,claimed_at,
                          claimed_bridge_id,lease_until,completed_at,result_json,error,
                          retry_safe,claim_token
                   FROM jobs WHERE owner=? AND job_id=?""",
                (str(owner or ""), str(job_id or "")),
            ).fetchone()
        if not row:
            return None
        return {
            "job_id": row["job_id"],
            "bridge_id": row["bridge_id"],
            "kind": row["kind"],
            "status": row["status"],
            "attempts": int(row["attempts"]),
            "created_at": int(row["created_at"]),
            "claimed_at": int(row["claimed_at"]) if row["claimed_at"] else None,
            "claimed_bridge_id": row["claimed_bridge_id"],
            "lease_until": int(row["lease_until"]) if row["lease_until"] else None,
            "completed_at": int(row["completed_at"]) if row["completed_at"] else None,
            "result": _json_load(row["result_json"], {}),
            "error": row["error"] or "",
            "retry_safe": bool(row["retry_safe"]),
            "claim_active": bool(row["claim_token"]),
        }

    def wait(self, owner: str, job_id: str, *, timeout: float = 45.0, poll: float = 0.15) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            row = self.get_job(owner, job_id)
            if not row:
                raise ValueError("Job was not found.")
            if row["status"] in {"completed", "failed", "uncertain"}:
                return row
            time.sleep(max(0.05, min(float(poll), 1.0)))
        row = self.get_job(owner, job_id)
        if row:
            row["timed_out"] = True
            return row
        raise ValueError("Job was not found.")

    def revoke(self, owner: str, bridge_id: str | None = None) -> int:
        now = _now()
        with self._connect() as conn:
            if bridge_id:
                bridge_id = _safe_bridge_id(bridge_id)
                cur = conn.execute(
                    """UPDATE bridges SET revoked_at=? WHERE owner=? AND bridge_id=?
                       AND revoked_at IS NULL""",
                    (now, owner, bridge_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE bridges SET revoked_at=? WHERE owner=? AND revoked_at IS NULL",
                    (now, owner),
                )
            conn.execute(
                "UPDATE owner_state SET selected_bridge_id=NULL,selected_studio_id=NULL,updated_at=? WHERE owner=?",
                (now, owner),
            )
        return int(cur.rowcount or 0)


_DEFAULT_STORE: Any | None = None
_DEFAULT_LOCK = threading.Lock()


def _postgres_url() -> str:
    url = str(os.getenv("DATABASE_URL") or "").strip()
    return url if url.startswith(("postgresql://", "postgres://")) else ""


def default_store():
    """Use RONN_MEMORY Postgres in production; SQLite is a safe local/test fallback."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_STORE is None:
                url = _postgres_url()
                if url:
                    from roblox_bridge_store_pg import PostgresRobloxBridgeStore
                    _DEFAULT_STORE = PostgresRobloxBridgeStore(url)
                else:
                    _DEFAULT_STORE = RobloxBridgeStore()
    return _DEFAULT_STORE


def status() -> dict[str, Any]:
    backend = "postgres" if _postgres_url() else "sqlite"
    return {
        "version": VERSION,
        "backend": backend,
        "persistent_queue": True,
        "cross_deploy_durable": backend == "postgres",
        "pair_ttl_seconds": PAIR_TTL_SECONDS,
        "bridge_online_seconds": BRIDGE_ONLINE_SECONDS,
        "max_job_attempts": MAX_JOB_ATTEMPTS,
        "token_hashing": "sha256",
        "claim_generation_tokens": True,
        "unsafe_mutation_replay": False,
        "uncertain_mutation_state": True,
    }
