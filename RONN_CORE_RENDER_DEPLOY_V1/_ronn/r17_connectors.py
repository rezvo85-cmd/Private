"""RONN R17 universal connector registry."""
from __future__ import annotations
import os, requests

SPECS={
  "github":{"env":"GITHUB_TOKEN","label":"GitHub","capabilities":["repos","files","issues","pull_requests"]},
  "google":{"env":"GOOGLE_CONNECTOR_TOKEN","label":"Google Workspace","capabilities":["drive","gmail","calendar"]},
  "dropbox":{"env":"DROPBOX_ACCESS_TOKEN","label":"Dropbox","capabilities":["files"]},
  "slack":{"env":"SLACK_BOT_TOKEN","label":"Slack","capabilities":["messages","channels"]},
  "computer":{"env":"RONN_COMPUTER_TOKEN","label":"Computer Runtime","capabilities":["browser","desktop"]},
}

def status():
    out={}
    for key,s in SPECS.items():
        token=(os.getenv(s["env"]) or "").strip()
        out[key]={"label":s["label"],"configured":bool(token),"capabilities":s["capabilities"],"secret_exposed":False}
    return out

def github_request(method,path,payload=None):
    token=(os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:raise RuntimeError("GITHUB_TOKEN is not configured in RONN.")
    if not str(path).startswith("/"):path="/"+str(path)
    r=requests.request(method.upper(),"https://api.github.com"+path,
      headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"},
      json=payload,timeout=20)
    data=None
    try:data=r.json()
    except Exception:data={"text":r.text[:3000]}
    if not r.ok:raise RuntimeError(f"GitHub HTTP {r.status_code}: {str(data)[:400]}")
    return data
