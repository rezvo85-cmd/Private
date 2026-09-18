"""RONN R16 optional isolated full-code runner adapter.

The local Render process intentionally does not execute unrestricted project code.
When RONN_RUNNER_URL + RONN_RUNNER_TOKEN point at an isolated runner service,
RONN can send a bounded workspace there for real project execution.
"""
from __future__ import annotations
import os, requests

BASE=(os.getenv("RONN_RUNNER_URL") or "").strip().rstrip("/")
TOKEN=(os.getenv("RONN_RUNNER_TOKEN") or "").strip()

def configured():
    return bool(BASE and TOKEN)

def _headers():
    return {"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"}

def status():
    if not configured():
        return {"configured":False,"reachable":False,"verified":False,
                "message":"No isolated full-code runner is connected."}
    try:
        r=requests.get(BASE+"/health",headers=_headers(),timeout=6)
        return {"configured":True,"reachable":bool(r.ok),"verified":bool(r.ok),
                "http_status":r.status_code,
                "message":"Isolated runner verified." if r.ok else "Runner health check failed."}
    except requests.RequestException as exc:
        return {"configured":True,"reachable":False,"verified":False,"message":str(exc)[:180]}

def execute(files,entry,language="auto",timeout_s=30):
    if not configured():
        raise RuntimeError("RONN full-code runner is not configured.")
    payload={
      "files":[{"name":str(x.get("name",""))[:240],"content":str(x.get("content",""))[:700000]} for x in list(files or [])[:60]],
      "entry":str(entry)[:240],
      "language":str(language or "auto")[:30],
      "timeout_s":max(1,min(int(timeout_s),90)),
      "network":False,
      "limits":{"memory_mb":768,"cpu_seconds":20,"output_chars":40000}
    }
    r=requests.post(BASE+"/execute",headers=_headers(),json=payload,timeout=payload["timeout_s"]+15)
    if not r.ok:
        raise RuntimeError(f"Runner HTTP {r.status_code}: {r.text[:400]}")
    data=r.json()
    data["verified_remote_runner"]=True
    return data
