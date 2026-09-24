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
from r23_browser_use_adapter import execute as browser_use_execute, status as browser_use_status
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
        "interactive_browser_verified":bool(
            "browser_automation" in executed and (out.get("browser_automation") or {}).get("ok")
        ),
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


def evidence_sufficiency(out: dict[str,Any], decision: dict | None=None,
                         *, contract: dict[str,Any] | None=None, depth: str="smart") -> dict[str,Any]:
    """Decide whether tool evidence actually satisfies the requested evidence boundary.

    This is deliberately mechanical. It never invents evidence and never upgrades
    snippets/static analysis into runtime verification.
    """
    out=out or {}
    decision=decision or {}
    caps=decision.get("capabilities") or {}
    contract=contract or evidence_contract(out)
    retrieval=contract.get("retrieval") or {}
    runtime=contract.get("runtime_execution") or {}
    requirements=[]

    def require(name: str, met: bool, detail: str):
        requirements.append({"name":name,"met":bool(met),"detail":str(detail)[:220]})

    if decision.get("needs_live"):
        structured=bool(contract.get("structured_live_data"))
        read_pages=int(retrieval.get("read_page_count") or 0)
        explicit_pages=int(retrieval.get("explicit_browser_pages_read") or 0)
        min_reads=2 if caps.get("autonomous_research") and depth in {"deep","apex"} else 1
        live_met=bool(structured or explicit_pages>=1 or read_pages>=min_reads)
        require(
            "live_source_evidence",
            live_met,
            (
                "structured live data returned"
                if structured else
                f"{read_pages} research page(s) read; {min_reads} required at this depth"
            ),
        )

    if caps.get("browser_url"):
        read_pages=int(retrieval.get("explicit_browser_pages_read") or 0)
        interactive_verified=bool(contract.get("interactive_browser_verified"))
        require(
            "explicit_url_read",
            bool(read_pages>=1 or interactive_verified),
            (
                f"{read_pages} explicit URL page(s) successfully read"
                if read_pages>=1 else
                ("interactive browser execution verified" if interactive_verified else "explicit URL was not successfully read or interacted with")
            ),
        )

    if caps.get("agent_runtime") and caps.get("browser_interactive"):
        require(
            "interactive_browser_execution",
            bool(contract.get("interactive_browser_verified")),
            "bounded interactive browser task completed" if contract.get("interactive_browser_verified") else "interactive browser task did not complete successfully",
        )

    if caps.get("code_fix_loop") and decision.get("verify"):
        require(
            "runtime_verification",
            bool(runtime.get("verified_success")),
            "controlled runtime verified success" if runtime.get("verified_success") else "runtime verification was not completed successfully",
        )

    if caps.get("world_model"):
        require(
            "static_dependency_analysis",
            bool(contract.get("computed_static_analysis")),
            "world/dependency model computed" if contract.get("computed_static_analysis") else "world/dependency model was requested but not computed",
        )

    if caps.get("agent_runtime") and caps.get("computer_requested"):
        require(
            "computer_observation",
            bool(contract.get("computer_observation_verified")),
            "connected computer observation verified" if contract.get("computer_observation_verified") else "computer observation was not verified",
        )

    gaps=[x["name"] for x in requirements if not x["met"]]
    return {
        "version":"R23-EVIDENCE-SUFFICIENCY-1",
        "sufficient":not gaps,
        "requirements":requirements,
        "gaps":gaps,
        "required_count":len(requirements),
        "met_count":sum(1 for x in requirements if x["met"]),
        "reason":"all_required_evidence_present" if requirements and not gaps else (
            "no_strict_evidence_requirement" if not requirements else "required_evidence_missing"
        ),
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
        "browser_automation":{},
        "world_model":{},
        "simulation":{},
        "code_loop":{},
        "learning":{},
        "computer":{},
        "recovery":{},
        "evidence_contract":{},
        "evidence_sufficiency":{},
    }
    evidence=[]
    browser_use_state=browser_use_status()
    browser_use_ready=bool(browser_use_state.get("ready"))

    # 2) Full agent runtime: inspect explicit URLs with the safe browser.
    # Preserve the read-only path whenever the optional interactive executor
    # is not ready, so RONN still has page evidence instead of a dead end.
    urls=extract_urls(message)
    if urls and caps.get("agent_runtime") and (
        not caps.get("browser_interactive") or not browser_use_ready
    ):
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

    # Interactive web tasks use Browser Use only as a bounded executor. R23
    # still owns task selection, evidence requirements, and final synthesis.
    if caps.get("browser_interactive"):
        out["planned"].append("browser_automation")
        if not browser_use_ready:
            out["browser_automation"]={
                "ok":False,
                "reason":"unavailable",
                "installed":bool(browser_use_state.get("installed")),
                "enabled":bool(browser_use_state.get("enabled")),
                "configured":bool(browser_use_state.get("configured")),
            }
            out["errors"].append("browser_automation:unavailable")
        else:
            try:
                br=browser_use_execute(message,depth=depth)
                out["browser_automation"]=br
                if br.get("ok"):
                    out["executed"].append("browser_automation")
                    for url in br.get("urls") or []:
                        out["sources"].append({"url":url,"read":True,"kind":"browser_automation"})
                    evidence.append(
                        "RONN INTERACTIVE BROWSER EVIDENCE (bounded Browser Use executor; R23 remains final-answer owner):\n"+
                        json.dumps(br,ensure_ascii=False)[:32000]
                    )
                else:
                    out["errors"].append("browser_automation:"+str(br.get("reason") or "failed"))
            except Exception as exc:
                out["errors"].append("browser_automation:"+exc.__class__.__name__)

    # A configured Browser Use runtime can still fail at launch/runtime
    # (for example, missing Chromium). Fall back to the safe read-only browser
    # after the failed attempt, but never claim the requested interaction ran.
    if (
        urls
        and caps.get("agent_runtime")
        and caps.get("browser_interactive")
        and "browser_automation" not in out["executed"]
        and not out.get("browser_pages")
        and "browser" not in out["planned"]
    ):
        out["planned"].append("browser_fallback")
        try:
            pages=collect_pages(urls[:4])
            out["browser_pages"]=pages
            out["executed"].append("browser")
            evidence.append(
                "RONN BROWSER FALLBACK EVIDENCE (read-only; requested interaction was not verified):\n"+
                json.dumps(pages,ensure_ascii=False)[:30000]
            )
        except Exception as exc:
            out["errors"].append("browser_fallback:"+exc.__class__.__name__)

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

            # One bounded recovery pass when retrieval found no readable page.
            # This remains raw retrieval/page reading; no extra model is inserted.
            recovery_depth=(
                "deep" if depth in {"fast","smart"}
                else ("apex" if depth=="deep" else "")
            )
            weak_initial=bool(
                not rr.get("ok")
                or int(rr.get("read_count") or 0)<=0
            )
            if weak_initial and recovery_depth:
                recovery_info={
                    "attempted":True,
                    "from_depth":depth,
                    "to_depth":recovery_depth,
                    "used":False,
                }
                try:
                    rr2=autonomous_research(
                        message,
                        unknown_terms=retrieval.get("unknown_terms") or [],
                        depth=recovery_depth,
                    )
                    q1=(int(rr.get("read_count") or 0),int(rr.get("source_count") or 0))
                    q2=(int(rr2.get("read_count") or 0),int(rr2.get("source_count") or 0))
                    if q2>q1:
                        rr=rr2
                        recovery_info["used"]=True
                    recovery_info["final_read_count"]=int(rr.get("read_count") or 0)
                    recovery_info["final_source_count"]=int(rr.get("source_count") or 0)
                except Exception as recovery_exc:
                    recovery_info["error"]=recovery_exc.__class__.__name__
                out["recovery"]["research"]=recovery_info

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
    if caps.get("agent_runtime") and caps.get("code_fix_loop") and runnable:
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
    contract=evidence_contract(out)
    sufficiency=evidence_sufficiency(out,decision,contract=contract,depth=depth)
    contract["sufficiency"]=sufficiency
    out["evidence_contract"]=contract
    out["evidence_sufficiency"]=sufficiency
    return out


def status():
    cs=computer_status()
    bu=browser_use_status()
    return {
        "version":"R23-AGENT-3",
        "browser":True,
        "browser_use":bu,
        "research":True,
        "controlled_code_execution":True,
        "code_autofix":True,
        "world_model":True,
        "change_simulation":True,
        "verified_failure_learning":True,
        "computer_adapter":True,
        "computer_verified":bool(cs.get("verified")),
        "evidence_contract":True,
        "evidence_sufficiency_gate":True,
        "bounded_research_recovery":True,
    }
