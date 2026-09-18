"""RONN R16 bounded code -> test -> repair -> retest loop."""
from __future__ import annotations
import re
from r16_workspace import read, write, run

def _extract_code(text):
    s=str(text or "").strip()
    m=re.search(r"```(?:python|py|javascript|js)?\s*\n([\s\S]*?)\n```",s,re.I)
    return (m.group(1) if m else s).strip()

def loop(owner,workspace,entry,repair_fn,max_attempts=3):
    attempts=[]
    for i in range(max(1,min(int(max_attempts),4))):
        result=run(owner,workspace,entry,"auto",True)
        attempts.append({"attempt":i+1,"run":result})
        if result.get("ok"):
            return {"ok":True,"verified":True,"attempts":attempts,"entry":entry}
        current=read(owner,workspace,entry)["content"]
        prompt=f"""Repair this file so it runs successfully. Return ONLY the complete corrected file contents.
Do not use network, subprocess, filesystem APIs, environment secrets, or external packages.
FILE: {entry}
ERROR:
{result.get('stderr') or result.get('error') or result.get('stdout')}

CURRENT FILE:
{current}
"""
        fixed=_extract_code(repair_fn(prompt))
        if not fixed or fixed==current:
            return {"ok":False,"verified":True,"attempts":attempts,"error":"Repair model did not produce a different complete file."}
        change=write(owner,workspace,entry,fixed)
        attempts[-1]["repair_action_id"]=change.get("action_id")
    final=run(owner,workspace,entry,"auto",True)
    attempts.append({"attempt":"final","run":final})
    return {"ok":bool(final.get("ok")),"verified":True,"attempts":attempts,"entry":entry}
