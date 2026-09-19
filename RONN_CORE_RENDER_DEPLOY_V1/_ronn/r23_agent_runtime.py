"""RONN R23 unified agent runtime.

This module is the capability plane under the main brain. It performs only real,
bounded actions: live research/page reading, project dependency modeling,
controlled code execution/autofix, and verified remote-computer status/actions
when that separate runtime is configured.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from r16_workspace import write as ws_write, read as ws_read, run as ws_run
from r16_autofix import loop as autofix_loop
from r16_simulation import project_model, simulate as simulate_changes
from r17_computer import status as computer_status, action as computer_action
from r18_research import extract_urls, collect_pages
from r20_tool_hub import weather as weather_tool
from r23_research import research as autonomous_research
from experience_engine import learn_lesson


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


def _http_status_ok(value) -> bool:
    if value is None:
        return True
    try:
        code=int(value)
    except (TypeError,ValueError):
        return False
    return 200 <= code < 400


def evidence_contract(out: dict[str,Any]) -> dict[str,Any]:
    """Summarize what this turn actually observed versus merely retrieved."""
    out=out or {}
    research=out.get("research") or {}
    sources=list(research.get("sources") or [])
    read_sources=sum(1 for x in sources if isinstance(x,dict) and x.get("read"))
    snippet_only=sum(1 for x in sources if isinstance(x,dict) and not x.get("read"))

    browser_pages=list(out.get("browser_pages") or [])
    browser_read=sum(
        1 for x in browser_pages
        if isinstance(x,dict)
        and not x.get("error")
        and bool(x.get("text"))
        and _http_status_ok(x.get("status"))
    )

    executed=set(str(x) for x in (out.get("executed") or []))
    code=out.get("code_loop") or {}
    autofix=code.get("autofix") or {}
    final_runtime_verified=bool(
        code.get("ok")
        and (
            code.get("verified")
            or autofix.get("verified")
            or autofix.get("runtime_verified")
            or autofix.get("final_verified")
        )
    )

    return {
        "version":"R23-EVIDENCE-CONTRACT-1",
        "retrieval":{
            "source_count":len(sources),
            "read_page_count":read_sources,
            "snippet_only_count":snippet_only,
            "explicit_browser_pages_read":browser_read,
        },
        "structured_live_data":bool("weather" in executed),
        "computed_static_analysis":bool("world_model" in executed or "change_simulation" in executed),
        "runtime_execution":{
            "attempted":bool("code_test_fix_retest" in executed or code),
            "reported_ok":bool(code.get("ok")) if code else False,
            "verified_success":final_runtime_verified,
        },
        "computer_observation_verified":bool(
            "computer_runtime_inspect" in executed and (out.get("computer") or {}).get("verified")
        ),
        "errors":[str(x)[:180] for x in (out.get("errors") or [])[:8]],
        "rules":[
            "SEARCH SNIPPET ONLY is discovery evidence, not proof of page contents.",
            "READ PAGE means content was retrieved from that URL; it is source evidence, not runtime verification.",
            "Structured live data supports only the fields actually returned by that tool/API.",
            "Computed static analysis is derived evidence, not proof that changed code executed successfully.",
            "Use the word verified for execution success only when runtime_execution.verified_success is true or another explicit verified tool result proves the claim.",
            "If evidence is incomplete or conflicting, state the limitation instead of filling the gap from confidence.",
        ],
    }


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
        "simulation":{},
        "code_loop":{},
        "learning":{},
        "computer":{},
        "evidence_contract":{},
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

            # 8) Simulate the actual before/after project slice after a repair.
            before_files=[{"name":name,"content":content} for name,content in runnable[:40]]
            after_files=[]
            for name,_content in runnable[:40]:
                try:
                    after_files.append({"name":name,"content":ws_read(owner,workspace,name).get("content","")})
                except Exception:
                    after_files.append({"name":name,"content":_content})
            try:
                sim=simulate_changes(before_files,after_files)
                out["simulation"]=sim
                if sim.get("changes"):
                    out["executed"].append("change_simulation")
                    evidence.append(
                        "RONN CHANGE SIMULATION (computed from the verified workspace before/after files):\n"+
                        json.dumps(sim,ensure_ascii=False)[:26000]
                    )
            except Exception as exc:
                out["errors"].append("simulation:"+exc.__class__.__name__)

            # 9) Learn from the verified execution result. The lesson is compact,
            # evidence-bound, and keyed to the real runtime error signature.
            initial_error=str(
                first.get("stderr") or first.get("error") or first.get("stdout") or ""
            ).strip()
            if initial_error:
                normalized=re.sub(r"\s+"," ",initial_error)[:500]
                signature=hashlib.sha256((entry+"|"+normalized.lower()).encode("utf-8")).hexdigest()[:20]
                if result.get("ok"):
                    lesson=(
                        "A controlled test/fix/retest succeeded for a similar runtime failure in "
                        + entry + ". Initial verified error: " + normalized[:320]
                        + ". Preserve surrounding interfaces and rerun tests after applying a comparable repair."
                    )
                    confidence=.82
                    outcome="repair_succeeded"
                else:
                    lesson=(
                        "A controlled repair attempt did not verify success for a similar failure in "
                        + entry + ". Verified error: " + normalized[:320]
                        + ". Do not claim completion; inspect dependencies, runtime limits, and the failing contract."
                    )
                    confidence=.72
                    outcome="repair_unresolved"
                learn_lesson("coding",signature,lesson,confidence)
                out["learning"]={"signature":signature,"outcome":outcome,"confidence":confidence}
                out["executed"].append("failure_learning")

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
    out["evidence_contract"]=evidence_contract(out)
    return out


def status():
    cs=computer_status()
    return {
        "version":"R23-AGENT-2",
        "browser":True,
        "research":True,
        "controlled_code_execution":True,
        "code_autofix":True,
        "world_model":True,
        "change_simulation":True,
        "verified_failure_learning":True,
        "computer_adapter":True,
        "computer_verified":bool(cs.get("verified")),
        "evidence_contract":True,
    }
