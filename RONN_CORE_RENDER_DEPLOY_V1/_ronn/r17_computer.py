"""RONN R17 remote-computer transport.

RONN never fakes computer control. This adapter is active only when an isolated
remote-computer service is explicitly configured.
"""
from __future__ import annotations
import os, requests

BASE=(os.getenv("RONN_COMPUTER_URL") or "").strip().rstrip("/")
TOKEN=(os.getenv("RONN_COMPUTER_TOKEN") or "").strip()

def configured():
    return bool(BASE and TOKEN)

def _headers():
    return {"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"}

def status():
    if not configured():
        return {"configured":False,"reachable":False,"verified":False,
                "message":"No isolated computer runtime is connected."}
    try:
        r=requests.get(BASE+"/health",headers=_headers(),timeout=6)
        return {"configured":True,"reachable":bool(r.ok),"verified":bool(r.ok),
                "http_status":r.status_code,"message":"Computer runtime verified." if r.ok else "Computer runtime did not pass health check."}
    except requests.RequestException as exc:
        return {"configured":True,"reachable":False,"verified":False,"message":str(exc)[:180]}

def action(kind,payload=None):
    if not configured():raise RuntimeError("RONN computer runtime is not configured.")
    safe_kind=str(kind or "").strip().lower()
    if safe_kind not in {"navigate","click","type","keypress","screenshot","download","upload","wait","inspect"}:
        raise ValueError("Unsupported computer action.")
    r=requests.post(BASE+"/action",headers=_headers(),json={"action":safe_kind,"payload":payload or {}},timeout=60)
    if not r.ok:raise RuntimeError(f"Computer runtime HTTP {r.status_code}: {r.text[:250]}")
    return r.json()
