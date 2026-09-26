"""Durable PostgreSQL backend for RONN's Roblox Studio bridge state/queue."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

VERSION = "RONN-ROBLOX-BRIDGE-PG-2"
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


def _json_load(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
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


class PostgresRobloxBridgeStore:
    backend = "postgres"

    def __init__(self, url: str):
        self.url = str(url or "").strip()
        if not self.url.startswith(("postgresql://", "postgres://")):
            raise ValueError("A PostgreSQL DATABASE_URL is required.")
        self._initialized = False
        self._init()

    def _connect(self):
        return psycopg.connect(
            self.url,
            row_factory=dict_row,
            connect_timeout=8,
        )

    def _init(self):
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ronn_roblox_pair_codes(
                        code_hash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL,
                        used_at BIGINT
                    );
                    CREATE INDEX IF NOT EXISTS idx_ronn_roblox_pair_owner
                        ON ronn_roblox_pair_codes(owner, expires_at);

                    CREATE TABLE IF NOT EXISTS ronn_roblox_bridges(
                        token_hash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        bridge_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        last_seen BIGINT NOT NULL,
                        revoked_at BIGINT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        UNIQUE(owner, bridge_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_ronn_roblox_bridge_owner
                        ON ronn_roblox_bridges(owner, last_seen DESC);

                    CREATE TABLE IF NOT EXISTS ronn_roblox_owner_state(
                        owner TEXT PRIMARY KEY,
                        selected_bridge_id TEXT,
                        selected_studio_id TEXT,
                        updated_at BIGINT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS ronn_roblox_jobs(
                        job_id TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        bridge_id TEXT,
                        kind TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL,
                        available_at BIGINT NOT NULL,
                        claimed_at BIGINT,
                        claimed_bridge_id TEXT,
                        lease_until BIGINT,
                        completed_at BIGINT,
                        result_json TEXT,
                        error TEXT,
                        retry_safe BOOLEAN NOT NULL DEFAULT TRUE,
                        claim_token TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_ronn_roblox_jobs_pull
                        ON ronn_roblox_jobs(owner, status, available_at, created_at);
                    CREATE INDEX IF NOT EXISTS idx_ronn_roblox_jobs_owner
                        ON ronn_roblox_jobs(owner, created_at DESC);
                    """
                )
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE ronn_roblox_jobs ADD COLUMN IF NOT EXISTS retry_safe BOOLEAN NOT NULL DEFAULT TRUE")
                cur.execute("ALTER TABLE ronn_roblox_jobs ADD COLUMN IF NOT EXISTS claim_token TEXT")
            conn.commit()
        self._initialized = True

    def start_pairing(self, owner: str) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("Owner is required.")
        code = "".join(secrets.choice(_PAIR_ALPHABET) for _ in range(12))
        now = _now()
        expires = now + PAIR_TTL_SECONDS
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ronn_roblox_pair_codes WHERE owner=%s AND (used_at IS NULL OR expires_at<%s)",
                    (owner, now),
                )
                cur.execute(
                    """INSERT INTO ronn_roblox_pair_codes(
                        code_hash,owner,created_at,expires_at,used_at
                    ) VALUES(%s,%s,%s,%s,NULL)""",
                    (_digest(code), owner, now, expires),
                )
            conn.commit()
        return {
            "pair_code": code,
            "expires_at": expires,
            "expires_in": PAIR_TTL_SECONDS,
        }

    def pair_bridge(self, pair_code: str, bridge_id: str, name: str = "", metadata=None) -> dict[str, Any]:
        bridge_id = _safe_bridge_id(bridge_id)
        code_hash = _digest(str(pair_code or "").strip().upper())
        now = _now()
        token = secrets.token_urlsafe(32)
        token_hash = _digest(token)
        metadata_json = _json_dump(metadata or {}, limit=256 * 1024)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT owner,expires_at,used_at
                       FROM ronn_roblox_pair_codes
                       WHERE code_hash=%s
                       FOR UPDATE""",
                    (code_hash,),
                )
                row = cur.fetchone()
                if not row or row["used_at"] is not None or int(row["expires_at"]) < now:
                    conn.rollback()
                    raise ValueError("Pairing code is invalid or expired.")

                owner = str(row["owner"])
                cur.execute(
                    "UPDATE ronn_roblox_pair_codes SET used_at=%s WHERE code_hash=%s",
                    (now, code_hash),
                )
                # Re-pairing an install invalidates only that install's old token.
                cur.execute(
                    "DELETE FROM ronn_roblox_bridges WHERE owner=%s AND bridge_id=%s",
                    (owner, bridge_id),
                )
                cur.execute(
                    """INSERT INTO ronn_roblox_bridges(
                        token_hash,owner,bridge_id,name,created_at,last_seen,revoked_at,metadata_json
                    ) VALUES(%s,%s,%s,%s,%s,%s,NULL,%s)""",
                    (
                        token_hash,
                        owner,
                        bridge_id,
                        _safe_label(name),
                        now,
                        now,
                        metadata_json,
                    ),
                )
                cur.execute(
                    """INSERT INTO ronn_roblox_owner_state(
                        owner,selected_bridge_id,selected_studio_id,updated_at
                    ) VALUES(%s,%s,NULL,%s)
                    ON CONFLICT(owner) DO UPDATE SET
                        selected_bridge_id=EXCLUDED.selected_bridge_id,
                        selected_studio_id=NULL,
                        updated_at=EXCLUDED.updated_at""",
                    (owner, bridge_id, now),
                )
            conn.commit()

        return {
            "owner": owner,
            "bridge_id": bridge_id,
            "token": token,
            "paired_at": now,
        }

    def authenticate(self, token: str) -> dict[str, Any] | None:
        token = str(token or "").strip()
        if len(token) < 20:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT owner,bridge_id,name,created_at,last_seen,metadata_json
                       FROM ronn_roblox_bridges
                       WHERE token_hash=%s AND revoked_at IS NULL""",
                    (_digest(token),),
                )
                row = cur.fetchone()
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
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE ronn_roblox_bridges
                       SET last_seen=%s,metadata_json=%s
                       WHERE owner=%s AND bridge_id=%s AND revoked_at IS NULL""",
                    (now, metadata_json, auth["owner"], auth["bridge_id"]),
                )
            conn.commit()
        auth.update({"last_seen": now, "metadata": payload})
        return auth

    def status(self, owner: str) -> dict[str, Any]:
        owner = str(owner or "")
        now = _now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT bridge_id,name,created_at,last_seen,metadata_json
                       FROM ronn_roblox_bridges
                       WHERE owner=%s AND revoked_at IS NULL
                       ORDER BY last_seen DESC""",
                    (owner,),
                )
                rows = cur.fetchall()
                cur.execute(
                    """SELECT selected_bridge_id,selected_studio_id
                       FROM ronn_roblox_owner_state WHERE owner=%s""",
                    (owner,),
                )
                state = cur.fetchone()

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

        return {
            "version": VERSION,
            "backend": self.backend,
            "online": any(x["online"] and x["mcp_connected"] for x in bridges),
            "bridges": bridges,
            "selected_bridge_id": (
                str(state["selected_bridge_id"])
                if state and state["selected_bridge_id"]
                else None
            ),
            "selected_studio_id": (
                str(state["selected_studio_id"])
                if state and state["selected_studio_id"]
                else None
            ),
        }

    def select_studio(self, owner: str, bridge_id: str, studio_id: str) -> dict[str, Any]:
        bridge_id = _safe_bridge_id(bridge_id)
        studio_id = str(studio_id or "").strip()
        if not studio_id or len(studio_id) > 240:
            raise ValueError("Invalid Studio id.")

        status = self.status(owner)
        bridge = next(
            (
                x
                for x in status["bridges"]
                if x["bridge_id"] == bridge_id and x["online"] and x["mcp_connected"]
            ),
            None,
        )
        if not bridge:
            raise ValueError("That RONN Roblox bridge is not online.")

        ids = {
            str(x.get("studio_id") or x.get("id") or "")
            for x in bridge.get("studios") or []
            if isinstance(x, dict)
        }
        if studio_id not in ids:
            raise ValueError("That Roblox Studio window is no longer connected.")

        now = _now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ronn_roblox_owner_state(
                        owner,selected_bridge_id,selected_studio_id,updated_at
                    ) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(owner) DO UPDATE SET
                        selected_bridge_id=EXCLUDED.selected_bridge_id,
                        selected_studio_id=EXCLUDED.selected_studio_id,
                        updated_at=EXCLUDED.updated_at""",
                    (owner, bridge_id, studio_id, now),
                )
            conn.commit()
        return {
            "bridge_id": bridge_id,
            "studio_id": studio_id,
            "selected": True,
        }

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
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ronn_roblox_jobs(
                        job_id,owner,bridge_id,kind,payload_json,status,attempts,
                        created_at,available_at,retry_safe,claim_token
                    ) VALUES(%s,%s,%s,%s,%s,'queued',0,%s,%s,%s,NULL)""",
                    (job_id, owner, bridge_id, kind, raw, now, now, bool(retry_safe)),
                )
            conn.commit()
        return {
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
        }

    def _requeue_expired(self, cur, now: int):
        cur.execute(
            """SELECT job_id,attempts,retry_safe,claim_token FROM ronn_roblox_jobs
               WHERE status='claimed' AND lease_until IS NOT NULL AND lease_until<%s
               FOR UPDATE SKIP LOCKED""",
            (now,),
        )
        rows = cur.fetchall()
        for row in rows:
            if not bool(row["retry_safe"]):
                cur.execute(
                    """UPDATE ronn_roblox_jobs
                       SET status='uncertain',completed_at=%s,error=%s,
                           lease_until=NULL
                       WHERE job_id=%s AND status='claimed' AND claim_token=%s""",
                    (
                        now,
                        "Mutation delivery became uncertain after the bridge lease expired; inspect Studio state before any further edit.",
                        row["job_id"],
                        row["claim_token"],
                    ),
                )
            elif int(row["attempts"]) >= MAX_JOB_ATTEMPTS:
                cur.execute(
                    """UPDATE ronn_roblox_jobs
                       SET status='failed',completed_at=%s,error=%s,
                           claimed_bridge_id=NULL,lease_until=NULL,claim_token=NULL
                       WHERE job_id=%s""",
                    (now, "Bridge lease expired too many times.", row["job_id"]),
                )
            else:
                cur.execute(
                    """UPDATE ronn_roblox_jobs
                       SET status='queued',available_at=%s,
                           claimed_at=NULL,claimed_bridge_id=NULL,lease_until=NULL,
                           claim_token=NULL
                       WHERE job_id=%s""",
                    (now + 1, row["job_id"]),
                )

    def pull(
        self,
        token: str,
        *,
        limit: int = 1,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> list[dict[str, Any]]:
        auth = self.authenticate(token)
        if not auth:
            raise PermissionError("Bridge token is invalid or revoked.")

        limit = max(1, min(int(limit or 1), 4))
        lease_seconds = max(
            20,
            min(int(lease_seconds or DEFAULT_LEASE_SECONDS), 300),
        )
        now = _now()

        with self._connect() as conn:
            with conn.cursor() as cur:
                self._requeue_expired(cur, now)
                cur.execute(
                    """SELECT job_id,kind,payload_json,attempts,created_at
                       FROM ronn_roblox_jobs
                       WHERE owner=%s AND status='queued' AND available_at<=%s
                         AND (bridge_id IS NULL OR bridge_id=%s)
                       ORDER BY created_at ASC
                       FOR UPDATE SKIP LOCKED
                       LIMIT %s""",
                    (auth["owner"], now, auth["bridge_id"], limit),
                )
                rows = cur.fetchall()

                out = []
                for row in rows:
                    lease_until = now + lease_seconds
                    claim_token = secrets.token_urlsafe(24)
                    cur.execute(
                        """UPDATE ronn_roblox_jobs
                           SET status='claimed',claimed_at=%s,claimed_bridge_id=%s,
                               lease_until=%s,attempts=attempts+1,claim_token=%s
                           WHERE job_id=%s AND status='queued'""",
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
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT owner,status,claimed_bridge_id,claim_token,retry_safe
                       FROM ronn_roblox_jobs WHERE job_id=%s
                       FOR UPDATE""",
                    (job_id,),
                )
                row = cur.fetchone()
                if not row or row["owner"] != auth["owner"]:
                    conn.rollback()
                    raise ValueError("Job was not found.")

                if row["status"] in {"completed", "failed"}:
                    conn.rollback()
                    return self.get_job(auth["owner"], job_id) or {
                        "job_id": job_id,
                        "status": row["status"],
                    }

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

                status = "failed" if error else "completed"
                cur.execute(
                    """UPDATE ronn_roblox_jobs
                       SET status=%s,completed_at=%s,result_json=%s,error=%s,
                           lease_until=NULL
                       WHERE job_id=%s AND claim_token=%s""",
                    (status, now, result_json, error, job_id, current_claim),
                )
            conn.commit()

        return self.get_job(auth["owner"], job_id) or {
            "job_id": job_id,
            "status": status,
        }

    def get_job(self, owner: str, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT job_id,bridge_id,kind,status,attempts,created_at,claimed_at,
                              claimed_bridge_id,lease_until,completed_at,result_json,error,
                              retry_safe,claim_token
                       FROM ronn_roblox_jobs
                       WHERE owner=%s AND job_id=%s""",
                    (str(owner or ""), str(job_id or "")),
                )
                row = cur.fetchone()

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

    def wait(
        self,
        owner: str,
        job_id: str,
        *,
        timeout: float = 45.0,
        poll: float = 0.15,
    ) -> dict[str, Any]:
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
            with conn.cursor() as cur:
                if bridge_id:
                    bridge_id = _safe_bridge_id(bridge_id)
                    cur.execute(
                        """UPDATE ronn_roblox_bridges
                           SET revoked_at=%s
                           WHERE owner=%s AND bridge_id=%s AND revoked_at IS NULL""",
                        (now, owner, bridge_id),
                    )
                else:
                    cur.execute(
                        """UPDATE ronn_roblox_bridges
                           SET revoked_at=%s
                           WHERE owner=%s AND revoked_at IS NULL""",
                        (now, owner),
                    )
                count = int(cur.rowcount or 0)
                cur.execute(
                    """UPDATE ronn_roblox_owner_state
                       SET selected_bridge_id=NULL,selected_studio_id=NULL,updated_at=%s
                       WHERE owner=%s""",
                    (now, owner),
                )
            conn.commit()
        return count
