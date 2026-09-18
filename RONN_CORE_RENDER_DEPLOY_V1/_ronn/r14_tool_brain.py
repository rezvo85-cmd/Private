"""RONN R14 automatic tool-selection brain."""
from __future__ import annotations
import re

def plan(message, profile="chat", has_files=False, has_images=False, current=False, agent_mode=True):
    low=re.sub(r"\s+"," ",str(message or "").lower())
    tools=[]
    def add(name,reason,automatic=False):
        if not any(x["tool"]==name for x in tools):
            tools.append({"tool":name,"reason":reason,"automatic":bool(automatic)})
    if has_images: add("vision","Images/screenshots need multimodal inspection",True)
    if has_files: add("file_project_graph","Attached files should be analyzed as one dependency graph",True)
    if current or any(x in low for x in ("latest","today","current","right now","news","price","version")):
        add("live_research","Changing facts require fresh evidence",True)
    if any(x in low for x in ("calculate","equation","percent","math","formula")):
        add("calculator","Deterministic math is preferable to model arithmetic",True)
    if "json" in low: add("json_validator","Structured JSON can be validated deterministically",True)
    if profile=="coding" or any(x in low for x in ("code","script","debug","traceback","syntax","function","api")):
        add("safe_code_sandbox","Code benefits from executable checks when compatible",False)
        add("project_graph","Trace components, files and prior fixes",True)
    if any(x in low for x in ("remember","previous","before","our project","continue")):
        add("memory_graph","Use durable project/user context",True)
    if any(x in low for x in ("plan","steps","multi-step","build","deploy","fix everything")) and agent_mode:
        add("task_agent","Create checkpoints and execute safe reversible local steps",True)
    if any(x in low for x in ("verify","double check","reliable","make sure","wrong","test")):
        add("critic","Run an independent verification pass",True)
    return {"tools":tools[:8],"count":len(tools),"agent_mode":bool(agent_mode)}

def directive(p):
    if not p.get("tools"): return "RONN TOOL BRAIN: No special tool is required; answer directly."
    lines=["RONN TOOL BRAIN selected these capabilities:"]
    for x in p["tools"]:
        lines.append(f"- {x['tool']}: {x['reason']}")
    lines.append("Use tools only when actually available. Never claim a tool ran unless a real result exists.")
    return "\n".join(lines)
