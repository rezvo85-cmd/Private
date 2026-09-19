import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
BOOTSTRAP = BASE / "owner_bootstrap.json"


def _config():
    try:
        return json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    except Exception:
        return {}


def owner_name():
    return str(_config().get("owner_display_name") or "Owner")


def verify_secret(secret: str) -> bool:
    cfg = _config()
    secret = str(secret or "")
    if not secret or cfg.get("algorithm") != "pbkdf2_sha256":
        return False
    try:
        salt = base64.urlsafe_b64decode(cfg["salt_b64"])
        expected = base64.urlsafe_b64decode(cfg["hash_b64"])
        got = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode("utf-8"),
            salt,
            int(cfg.get("iterations") or 480000),
            dklen=len(expected),
        )
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _session_signing_key() -> bytes:
    key = (os.getenv("RONN_SESSION_SIGNING_KEY") or os.getenv("RONN_CORE_TOKEN") or "").strip()
    return key.encode("utf-8")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_session_token(owner: str = "", client_id: str = "", device_id: str = "", days: int = 180) -> str:
    key = _session_signing_key()
    if not key:
        return "op_" + secrets.token_urlsafe(42)
    now = int(time.time())
    exp = now + max(1, min(int(days), 365)) * 86400
    payload = {
        "v": 1,
        "o": str(owner or "")[:160],
        "c": str(client_id or "")[:160],
        "d": str(device_id or "")[:160],
        "iat": now,
        "exp": exp,
        "n": secrets.token_urlsafe(18),
    }
    body = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64u(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
    return "ops1." + body + "." + sig


def verify_signed_session(token: str, owner: str | None = None):
    token = str(token or "")
    if not token.startswith("ops1."):
        return None
    key = _session_signing_key()
    if not key:
        return None
    try:
        _, body, sig = token.split(".", 2)
        expected = _b64u(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64u_decode(body).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        if owner and str(payload.get("o") or "") != str(owner):
            return None
        return payload
    except Exception:
        return None


def new_recovery_code() -> str:
    return "RONN-" + secrets.token_urlsafe(16).replace("_", "").replace("-", "")[:22].upper()
