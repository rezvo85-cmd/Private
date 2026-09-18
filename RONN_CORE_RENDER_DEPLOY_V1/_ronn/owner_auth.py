import base64
import hashlib
import hmac
import json
import secrets
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


def new_session_token() -> str:
    return "op_" + secrets.token_urlsafe(42)


def new_recovery_code() -> str:
    return "RONN-" + secrets.token_urlsafe(16).replace("_", "").replace("-", "")[:22].upper()
