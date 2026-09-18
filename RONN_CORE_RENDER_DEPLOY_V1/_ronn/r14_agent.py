"""RONN R14 safe multi-step task agent.

The executor only runs reversible local tools. External writes remain behind
separate explicit integrations/approval boundaries.
"""
from __future__ import annotations
import json, re, time
from r14_tool_brain import plan as tool_plan
from r14_sandbox import execute as run_python, SandboxError

def make_plan(message, profile="chat", has_files=False, has_images=False, current=False):
    tp=tool_plan(message,profile,has_files,has_images,current,True)
    steps=[{"step":"understand","status":"planned","action":"Resolve goal, context and constraints"}]
    for t in tp["tools"]:
        steps.append({"step":t["tool"],"status":"planned","action":t["reason"],"automatic":t["automatic"]})
    steps.append({"step":"verify","status":"planned","action":"Check result against requirements and evidence"})
    return {"version":"R14","steps":steps[:10],"tool_plan":tp}

def execute_local(command):
    text=str(command or "").strip()
    started=time.time()
    if text.lower().startswith("/runpy "):
        try:
            result=run_python(text[7:])
            return {"ok":True,"tool":"safe_code_sandbox","result":result,"ms":round((time.time()-started)*1000,2)}
        except (SandboxError,SyntaxError,ValueError) as exc:
            return {"ok":False,"tool":"safe_code_sandbox","error":str(exc)[:300]}
    return {"ok":False,"tool":"agent","error":"No safe executable command recognized. Supported: /runpy <restricted Python>."}
