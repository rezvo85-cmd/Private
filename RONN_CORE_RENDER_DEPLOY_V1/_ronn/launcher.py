import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from provider_models import normalize_groq_model

ROOT = Path(__file__).resolve().parent.parent
CORE = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
VENV = CORE / ".venv"
REQ = CORE / "requirements.txt"
LOGS = CORE / "logs"
RUNTIME_FILE = CORE / "data" / "runtime.json"
LOGS.mkdir(exist_ok=True)
RUNTIME_FILE.parent.mkdir(exist_ok=True)
BASE_PORT = 8030
BUILD_ID = "RONN-COGNITIVE-OS-2026-R23-ALL-11"


def python_cmd():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _parse_env_values(path: Path):
    values = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def _real_key(value: str):
    value = (value or "").strip()
    return bool(value and "PASTE_YOUR_" not in value.upper() and value.lower() not in {"none", "null", "changeme"})


def _env_has_provider(path: Path):
    vals = _parse_env_values(path)
    return any(_real_key(vals.get(k, "")) for k in ("CLOUD_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY"))


def shared_config_path():
    """Stable per-user provider config so upgrades do not lose the user's key."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "RONN" / "config.env"
    return Path.home() / ".config" / "ronn" / "config.env"


def _candidate_roots():
    roots = [ROOT.parent, ROOT.parent.parent]
    home = Path.home()
    for name in ("Downloads", "Desktop", "Documents"):
        q = home / name
        if q.exists():
            roots.append(q)
    out = []
    seen = set()
    for r in roots:
        try:
            rr = r.resolve()
        except Exception:
            rr = r
        key = str(rr).lower()
        if key not in seen and rr.exists():
            seen.add(key); out.append(rr)
    return out


def _walk_env_candidates(root: Path, max_depth=4, max_dirs=1200):
    """Find RONN/NOVA .env files without crawling the entire PC."""
    root = root.resolve()
    count = 0
    skip = {".venv", "venv", "node_modules", ".git", "__pycache__", "AppData", "Windows", "Program Files", "Program Files (x86)"}
    for current, dirs, files in os.walk(root):
        count += 1
        if count > max_dirs:
            break
        cur = Path(current)
        try:
            depth = len(cur.relative_to(root).parts)
        except Exception:
            depth = 99
        dirs[:] = [d for d in dirs if d not in skip and depth < max_depth]
        if ".env" not in files:
            continue
        p = cur / ".env"
        low = str(p).lower()
        if "ronn" in low or "nova" in low:
            yield p


def find_working_env():
    """Find the newest valid RONN/NOVA provider configuration without exposing a secret."""
    candidates = []
    shared = shared_config_path()
    if shared.exists() and _env_has_provider(shared):
        try: candidates.append((10**20, shared))
        except Exception: pass
    for root in _candidate_roots():
        try:
            for p in _walk_env_candidates(root):
                try:
                    if p.resolve() == ENV_FILE.resolve():
                        continue
                    if _env_has_provider(p):
                        candidates.append((p.stat().st_mtime, p))
                except Exception:
                    pass
        except Exception:
            pass
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1] if candidates else None


def clean_env_file():
    """Normalize known settings, migrate legacy NOVA_* names, and never print secrets."""
    if not ENV_FILE.exists():
        return
    allowed = {
        "CLOUD_API_BASE", "CLOUD_API_KEY", "GROQ_API_KEY",
        "NVIDIA_BASE_URL", "NVIDIA_API_KEY", "NVIDIA_MODEL",
        "OPENROUTER_API_BASE", "OPENROUTER_API_KEY", "RONN_CONTROLLER_OPENROUTER_MODEL",
        "RONN_PUBLIC_MODE", "RONN_RATE_LIMIT_PER_MINUTE", "RONN_MAX_BODY_BYTES",
        "RONN_FAST_MODEL", "RONN_SMART_MODEL", "RONN_CREATOR_MODEL",
        "RONN_VISION_MODEL", "RONN_LIVE_MODEL", "RONN_RESEARCH_MODEL",
        "RONN_STUDIO_BRIDGE_URL", "RONN_STUDIO_BRIDGE_TOKEN",
        "RONN_CORE_TOKEN", "RONN_CORS_ORIGINS", "RONN_CREDITS_ENABLED", "RONN_DEFAULT_CREDITS", "RONN_VAULT_MASTER_KEY",
        "PORT",
    }
    legacy_map = {
        "NOVA_PUBLIC_MODE": "RONN_PUBLIC_MODE",
        "NOVA_RATE_LIMIT_PER_MINUTE": "RONN_RATE_LIMIT_PER_MINUTE",
        "NOVA_MAX_BODY_BYTES": "RONN_MAX_BODY_BYTES",
        "NOVA_FAST_MODEL": "RONN_FAST_MODEL",
        "NOVA_SMART_MODEL": "RONN_SMART_MODEL",
        "NOVA_CREATOR_MODEL": "RONN_CREATOR_MODEL",
        "NOVA_VISION_MODEL": "RONN_VISION_MODEL",
        "NOVA_LIVE_MODEL": "RONN_LIVE_MODEL",
        "NOVA_RESEARCH_MODEL": "RONN_RESEARCH_MODEL",
    }
    values = {}
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = legacy_map.get(k.strip(), k.strip())
        v = v.strip().strip('"').strip("'")
        if k not in allowed or not v:
            continue
        if k in {"CLOUD_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "RONN_STUDIO_BRIDGE_TOKEN"} and any(x in v for x in (" ", "(", ")")):
            continue
        values[k] = v

    values.setdefault("CLOUD_API_BASE", "https://api.groq.com/openai/v1")
    values.setdefault("CLOUD_API_KEY", "PASTE_YOUR_GROQ_API_KEY_HERE")
    values.setdefault("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    values.setdefault("NVIDIA_API_KEY", "PASTE_YOUR_NVIDIA_API_KEY_HERE")
    values.setdefault("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")
    values.setdefault("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

    # Clean stale Groq model overrides during desktop launch too, so a recovered
    # old .env does not keep forcing retired IDs after the runtime was upgraded.
    groq_base=values.get("CLOUD_API_BASE", "https://api.groq.com/openai/v1")
    for key in (
        "RONN_FAST_MODEL","RONN_SMART_MODEL","RONN_CREATOR_MODEL",
        "RONN_VISION_MODEL","RONN_LIVE_MODEL","RONN_RESEARCH_MODEL",
    ):
        if values.get(key):
            values[key]=normalize_groq_model(values[key],groq_base)

    values["RONN_PUBLIC_MODE"] = "false"
    values.setdefault("RONN_CREDITS_ENABLED", "false")
    values.setdefault("RONN_DEFAULT_CREDITS", "100")
    values["PORT"] = "8030"

    ordered = [
        "CLOUD_API_BASE", "CLOUD_API_KEY", "GROQ_API_KEY",
        "NVIDIA_BASE_URL", "NVIDIA_API_KEY", "NVIDIA_MODEL",
        "OPENROUTER_API_BASE", "OPENROUTER_API_KEY", "RONN_CONTROLLER_OPENROUTER_MODEL",
        "RONN_FAST_MODEL", "RONN_SMART_MODEL", "RONN_CREATOR_MODEL",
        "RONN_VISION_MODEL", "RONN_LIVE_MODEL", "RONN_RESEARCH_MODEL",
        "RONN_RATE_LIMIT_PER_MINUTE", "RONN_MAX_BODY_BYTES",
        "RONN_STUDIO_BRIDGE_URL", "RONN_STUDIO_BRIDGE_TOKEN",
        "RONN_CORE_TOKEN", "RONN_CORS_ORIGINS", "RONN_CREDITS_ENABLED", "RONN_DEFAULT_CREDITS", "RONN_VAULT_MASTER_KEY",
        "RONN_PUBLIC_MODE", "PORT",
    ]
    lines = [f"{k}={values[k]}" for k in ordered if k in values]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def persist_shared_env():
    if not _env_has_provider(ENV_FILE):
        return None
    target = shared_config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ENV_FILE, target)
        return target
    except Exception:
        return None


def ensure_env():
    """Guarantee that RONN either has a real provider key or stops before opening a broken chat UI."""
    source = None
    # A placeholder .env from an earlier failed launch must not block migration.
    if not _env_has_provider(ENV_FILE):
        old = find_working_env()
        if old:
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, ENV_FILE)
            source = old
            print(f"[RONN] Recovered your existing provider configuration from: {old}")

    if not ENV_FILE.exists():
        ENV_FILE.write_text(
            "CLOUD_API_BASE=https://api.groq.com/openai/v1\n"
            "CLOUD_API_KEY=PASTE_YOUR_GROQ_API_KEY_HERE\n"
            "NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1\n"
            "NVIDIA_API_KEY=PASTE_YOUR_NVIDIA_API_KEY_HERE\n"
            "NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b\n"
            "RONN_PUBLIC_MODE=false\nPORT=8030\n",
            encoding="utf-8",
        )

    clean_env_file()
    configured = _env_has_provider(ENV_FILE)

    if not configured and os.name == "nt":
        print("[RONN] No AI provider key was found in this build or previous RONN/NOVA folders.")
        print(f"[RONN] Opening the exact configuration file now: {ENV_FILE}")
        print("[RONN] Paste your Groq key after CLOUD_API_KEY=, save, then CLOSE Notepad.")
        try:
            subprocess.call(["notepad.exe", str(ENV_FILE)])
        except Exception:
            pass
        clean_env_file()
        configured = _env_has_provider(ENV_FILE)

    if configured:
        shared = persist_shared_env()
        if shared:
            print(f"[RONN] Provider configuration persisted for future upgrades: {shared}")
        return {"configured": True, "source": str(source or ENV_FILE), "shared": str(shared or shared_config_path())}

    print("[RONN] No valid provider key is configured, so RONN will NOT open a nonfunctional chat window.")
    print(f"[RONN] Configure: {ENV_FILE}")
    return {"configured": False, "source": str(ENV_FILE), "shared": str(shared_config_path())}

def ensure_venv():
    py = python_cmd()
    if not py.exists():
        print("[RONN] First launch: creating a private Python environment...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    check = subprocess.run(
        [str(py), "-c", "import fastapi,uvicorn,requests,dotenv,cryptography"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode != 0:
        print("[RONN] Installing required packages...")
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", "-r", str(REQ)])
    return py


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port(start=BASE_PORT, end=8099):
    for port in range(start, end + 1):
        if port_is_free(port):
            return port
    raise RuntimeError("RONN could not find a free local port between 8030 and 8099.")


def health_data(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.25) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore") or "{}")
    except Exception:
        return {}


def wait_for_ronn(proc, port, seconds=40):
    for _ in range(seconds * 2):
        if proc.poll() is not None:
            return False
        data = health_data(port)
        if data.get("ok") is True and data.get("build") == BUILD_ID and data.get("name") == "RONN" and data.get("integrity_ok") is True:
            return True
        time.sleep(0.5)
    return False


def start_process(cmd, log_name, env=None):
    log = open(LOGS / log_name, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        cmd,
        cwd=str(CORE),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        env=env,
    )


def write_runtime(port, pid):
    RUNTIME_FILE.write_text(json.dumps({
        "name": "RONN",
        "build": BUILD_ID,
        "port": port,
        "pid": pid,
        "started_at": int(time.time()),
    }, indent=2), encoding="utf-8")


def main():
    if os.name == "nt":
        os.system("title RONN COGNITIVE OS APEX")
    print("=" * 68)
    print(" RONN COGNITIVE OS // R23 CORE API v1")
    print(" Agentic intelligence // research + snapshots + knowledge + verification")
    print("=" * 68)

    config = ensure_env()
    if not config.get("configured"):
        if os.name == "nt":
            input("\nPress Enter to close...")
        return
    py = ensure_venv()
    port = choose_port()
    if port != BASE_PORT:
        print(f"[RONN] Port {BASE_PORT} is occupied. Using {port} to avoid loading an old server.")

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["RONN_PUBLIC_MODE"] = "false"
    env["RONN_BUILD_ID"] = BUILD_ID
    env["RONN_ENV_FILE"] = str(ENV_FILE)
    env["RONN_ENV_SOURCE"] = config.get("source", str(ENV_FILE))
    env["RONN_SHARED_CONFIG"] = config.get("shared", str(shared_config_path()))

    proc = start_process([str(py), str(CORE / "app.py")], "ronn.log", env=env)
    print("[RONN] Starting server and verifying the exact build...")
    if wait_for_ronn(proc, port):
        write_runtime(port, proc.pid)
        url = f"http://127.0.0.1:{port}/?build={BUILD_ID}&t={int(time.time())}"
        print(f"[RONN] Verified build: {BUILD_ID}")
        print(f"[RONN] Ready: {url}")
        webbrowser.open(url)
        print("\nKeep this window open while using RONN.")
        try:
            while proc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        print("\n[RONN] Startup verification failed. A browser page was NOT opened.")
        print(f"Log: {LOGS / 'ronn.log'}")
        try:
            print("\n--- recent log ---")
            print((LOGS / "ronn.log").read_text(encoding="utf-8", errors="ignore")[-6000:])
        except Exception:
            pass
        if os.name == "nt":
            input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
