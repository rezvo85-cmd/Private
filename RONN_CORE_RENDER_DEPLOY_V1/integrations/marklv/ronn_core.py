"""Minimal client for the existing RONN Core v1 API.

Keeps R23 on Render as the reasoning brain while Mark-LV remains the local
voice/desktop shell. No provider keys are stored here; only the optional RONN
Core bearer token is read from the environment.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import requests

_BASE = Path(__file__).resolve().parent.parent
_STATE_FILE = _BASE / "config" / "ronn_client.json"
_DEFAULT_TIMEOUT = 90


def _stable_ids() -> tuple[str, str]:
    data: dict[str, Any] = {}
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    changed = False
    if not data.get("client_id"):
        data["client_id"] = "marklv-" + uuid.uuid4().hex
        changed = True
    if not data.get("device_id"):
        data["device_id"] = "pc-" + uuid.uuid4().hex
        changed = True

    if changed:
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
    return str(data["client_id"]), str(data["device_id"])


class RonnCoreError(RuntimeError):
    pass


class RonnCoreClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.getenv("RONN_CORE_URL", "")).strip().rstrip("/")
        self.token = (token if token is not None else os.getenv("RONN_CORE_TOKEN", "")).strip()
        self.client_id, self.device_id = _stable_ids()
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "X-RONN-Client": self.client_id,
            "X-RONN-Device": self.device_id,
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-RONN-Account"] = "ronn_primary"
        return headers

    def health(self, timeout: float = 12) -> dict[str, Any]:
        if not self.configured:
            raise RonnCoreError("RONN_CORE_URL is not configured on this PC.")
        try:
            r = self.session.get(
                self.base_url + "/api/v1/health",
                headers={k: v for k, v in self._headers().items() if k != "Content-Type"},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise RonnCoreError(f"Could not reach RONN Core: {exc}") from exc
        except ValueError as exc:
            raise RonnCoreError("RONN Core returned an invalid health response.") from exc

    def ask(
        self,
        message: str,
        *,
        project_id: str = "default",
        history: list[dict] | None = None,
        mode: str = "auto",
        style: str = "auto",
        project_context: str = "",
        agent_mode: bool = True,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        if not self.configured:
            raise RonnCoreError(
                "RONN Core is not connected yet. Set RONN_CORE_URL to the Render service URL."
            )
        payload = {
            "message": str(message or "").strip(),
            "project_id": project_id or "default",
            "history": history or [],
            "images": [],
            "files": [],
            "mode": mode or "auto",
            "style": style or "auto",
            "voice_session": True,
            "project_context": project_context or "",
            "review": False,
            "agent_mode": bool(agent_mode),
            "skill_profile": "auto",
            "client_location": {},
            "project_brain_snapshot": {},
            "outcome_profile": {},
        }
        if not payload["message"]:
            raise RonnCoreError("RONN needs a message to reason about.")
        try:
            r = self.session.post(
                self.base_url + "/api/v1/chat/complete",
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
            if r.status_code == 401:
                raise RonnCoreError(
                    "RONN Core rejected this PC. Configure RONN_CORE_TOKEN or reconnect the device."
                )
            if r.status_code >= 400:
                detail = ""
                try:
                    body = r.json()
                    detail = str(body.get("detail") or body.get("error") or "")
                except Exception:
                    detail = r.text[:240]
                raise RonnCoreError(f"RONN Core HTTP {r.status_code}: {detail or 'request failed'}")
            data = r.json()
        except RonnCoreError:
            raise
        except requests.RequestException as exc:
            raise RonnCoreError(f"Could not reach RONN Core: {exc}") from exc
        except ValueError as exc:
            raise RonnCoreError("RONN Core returned invalid JSON.") from exc

        answer = str(data.get("answer") or "").strip()
        if not answer:
            raise RonnCoreError("RONN Core returned no answer.")
        return data


_client: RonnCoreClient | None = None


def client() -> RonnCoreClient:
    """Return the process-wide RONN Core client used by Mark-LV actions."""
    global _client
    if _client is None:
        _client = RonnCoreClient()
    return _client
