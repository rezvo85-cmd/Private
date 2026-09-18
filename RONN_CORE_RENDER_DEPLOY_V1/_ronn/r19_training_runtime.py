"""RONN R19 optional external model-training runtime adapter."""
from __future__ import annotations
import os, requests

BASE=(os.getenv("RONN_TRAINING_URL") or "").strip().rstrip("/")
TOKEN=(os.getenv("RONN_TRAINING_TOKEN") or "").strip()

def configured():
    return bool(BASE and TOKEN)

def status():
    if not configured():
        return {"configured":False,"reachable":False,"training_available":False,
                "message":"No external RONN training runtime is connected."}
    try:
        r=requests.get(BASE+"/health",headers={"Authorization":"Bearer "+TOKEN},timeout=8)
        return {"configured":True,"reachable":bool(r.ok),"training_available":bool(r.ok),"http_status":r.status_code}
    except requests.RequestException as exc:
        return {"configured":True,"reachable":False,"training_available":False,"message":str(exc)[:180]}

def submit(dataset_jsonl,base_model="",job_name="RONN"):
    if not configured():raise RuntimeError("RONN training runtime is not configured.")
    r=requests.post(BASE+"/train",headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"},
                    json={"name":job_name,"base_model":base_model,"dataset_jsonl":dataset_jsonl},timeout=60)
    if not r.ok:raise RuntimeError(f"Training runtime HTTP {r.status_code}: {r.text[:300]}")
    return r.json()
