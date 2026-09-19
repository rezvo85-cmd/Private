"""RONN R23 unified agent runtime.

This module is the capability plane under the main brain. It performs only real,
bounded actions: live research/page reading, project dependency modeling,
controlled code execution/autofix, and verified remote-computer status/actions
when that separate runtime is configured.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from r16_workspace import write as ws_write, read as ws_read, run as ws_run
from r16_autofix import loop as autofix_loop
from r16_simulation import project_model
from r17_computer import status as computer_status, action as computer_action
from r18_research import extract_urls, collect_pages
from r20_tool_hub import weather as weather_tool
from r23_research import research as autonomous_research


def _item(f):
    if isinstance(f,dict):
        return str(f.get("name") or "file"), str(f.get("content") or "")
    return str(getattr(f,"name","file")), str(getattr(f,"content",""))


def _entry_score(name: str) -> tuple:
    low=name.lower().replace("\\","/")
    base=PurePosixPath(low).name
    preferred={
        "main.py":0,"app.py":1,"server.py":2,"index.js":3,"main.js":4,
        "app.js":5,"index.mjs":6,"main.mjs":7
    }
    return (preferred.get(base,50),len(low),low)


def _runnable(files):
    rows=[]
    for f in list(files or [])[:60]:
        name,content=_item(f)
        if name.lower().endswith((".py",".js",".mjs",".cjs")) and content.strip():
            rows.append((name,content))
    rows.sort(key=lambda x:_entry_score(x[0]))
    return rows


def execute(owner: str, request_id: str, message: str, files, decision: dict,
            *, depth="smart", repair_fn=None) -> dict[str,Any]:
    caps=(decision or {}).get("capabilities") or {}
    retrieval=(caps.get("retrieval") or {})
    out={
        "planned":[],
        "executed":[],
        "evidence":"",
        "sources":[],
        "errors":[],
        "research":{},
        "browser_pages":[],
        "world_model":{},
        "code_loop":{},
        "computer":{},
    }
    evidence=[]

    # 2) Full agent runtime: inspect explicit URLs with the safe browser.
    urls=extract_urls(message)
    if urls and caps.get("agent_runtime"):
        out["planned"].append("browser")
        try:
            pages=collect_pages(urls[:4])
            out["browser_pages"]=pages
            out["executed"].append("browser")
            evidence.append(
                "RONN BROWSER EVIDENCE:\n"+
                json.dumps(pages,ensure_ascii=False)[:30000]
            )
        except Exception as exc:
            out["errors"].append("browser:"+exc.__class__.__name__)

    # Weather stays structured instead of using generic search.
    low=str(message or "").lower()
    if decision.get("needs_live") and ("weather" in low or "forecast" in low):
        out["planned"].append("weather")
        try:
            wx=weather_tool(message)
            if wx.get("ok"):
                out["executed"].append("weather")
                out["sources"].extend(wx.get("sources") or [])
                evidence.append(str(wx.get("evidence") or ""))
            else:
                out["errors"].append("weather:"+str(wx.get("reason") or "failed"))
        except Exception as exc:
            out["errors"].append("weather:"+exc.__class__.__name__)

    # 10 + 11) Autonomous research / universal retrieval.
    if decision.get("needs_live") and not ("weather" in low or "forecast" in low):
        out["planned"].append("autonomous_research" if caps.get("autonomous_research") else "universal_retrieval")
        try:
            rr=autonomous_research(
                message,
                unknown_terms=retrieval.get("unknown_terms") or [],
                depth=depth,
            )
            out["research"]=rr
            if rr.get("ok"):
                out["executed"].append("autonomous_research" if caps.get("autonomous_research") else "universal_retrieval")
                out["sources"].extend(rr.get("sources") or [])
                evidence.append(str(rr.get("evidence") or ""))
            else:
                out["errors"].extend(rr.get("errors") or ["research:no_sources"])
        except Exception as exc:
            out["errors"].append("research:"+exc.__class__.__name__)

    # 8) Build a world/dependency model before large project/code changes.
    if caps.get("world_model") and files:
        out["planned"].append("world_model")
        try:
            world=project_model(list(files or []))
            out["world_model"]=world
            out["executed"].append("world_model")
            evidence.append(
                "RONN PROJECT WORLD MODEL (static dependency map; use it to reason about change impact):\n"+
                json.dumps(world,ensure_ascii=False)[:24000]
            )
        except Exception as exc:
            out["errors"].append("world_model:"+exc.__class__.__name__)

    # 3) Code -> test -> fix -> retest. Write the full runnable project slice,
    # then execute the best entry point. The repair loop is bounded.
    runnable=_runnable(files)
    if caps.get("code_fix_loop") and runnable:
        out["planned"].append("code_test_fix_retest")
        workspace="r23_"+str(request_id or "task")[-16:]
        try:
            writes=[]
            for name,content in runnable[:40]:
                writes.append(ws_write(owner,workspace,name,content))
            entry=runnable[0][0]
            first=ws_run(owner,workspace,entry,"auto",True)
            result={
                "workspace":workspace,
                "entry":entry,
                "files_written":len(writes),
                "initial_run":first,
                "verified":bool(first.get("verified")),
            }
            if not first.get("ok") and repair_fn is not None:
                fixed=autofix_loop(owner,workspace,entry,repair_fn,3)
                result["autofix"]=fixed
                try:
                    result["final_file"]=ws_read(owner,workspace,entry).get("content","")[:40000]
                except Exception:
                    pass
                result["ok"]=bool(fixed.get("ok"))
            else:
                result["ok"]=bool(first.get("ok"))
            out["code_loop"]=result
            out["executed"].append("code_test_fix_retest")
            evidence.append(
                "RONN CONTROLLED CODE EXECUTION EVIDENCE (real run results; do not overclaim beyond them):\n"+
                json.dumps(result,ensure_ascii=False)[:42000]
            )
        except Exception as exc:
            out["errors"].append("code_loop:"+exc.__class__.__name__)

    # 2) Computer runtime is real only when the isolated service is configured.
    if caps.get("computer_requested"):
        out["planned"].append("computer_runtime")
        try:
            cs=computer_status()
            out["computer"]=cs
            if cs.get("verified"):
                # Safe observation first. Mutating clicks/typing still require an
                # explicit downstream action request and permission boundary.
                shot=computer_action("screenshot",{})
                out["computer"]["screenshot"]=shot
                out["executed"].append("computer_runtime_inspect")
                evidence.append("RONN COMPUTER RUNTIME EVIDENCE:\n"+json.dumps(out["computer"],ensure_ascii=False)[:16000])
            else:
                out["errors"].append("computer_runtime:not_configured_or_unreachable")
        except Exception as exc:
            out["errors"].append("computer_runtime:"+exc.__class__.__name__)

    out["evidence"]="\n\n".join(x for x in evidence if x)[:110000]
    out["sources"]=out["sources"][:16]
    return out


def status():
    cs=computer_status()
    return {
        "version":"R23-AGENT-1",
        "browser":True,
        "research":True,
        "controlled_code_execution":True,
        "code_autofix":True,
        "world_model":True,
        "computer_adapter":True,
        "computer_verified":bool(cs.get("verified")),
    }
