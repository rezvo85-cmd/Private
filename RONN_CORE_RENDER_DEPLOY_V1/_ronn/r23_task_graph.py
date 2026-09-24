"""R23 Task Graph + bounded replanning controller.

The graph is deterministic orchestration metadata under the selected main brain.
It does not replace the model's reasoning. It tracks dependencies, tool/evidence
proofs, failed branches, one bounded recovery pass, and the remaining work needed
before final synthesis.
"""
from __future__ import annotations

import copy
from typing import Any

VERSION="R23-TASK-GRAPH-1"
MAX_NODES=14


def _unique(items):
    out=[]
    seen=set()
    for item in items:
        key=str(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def should_activate(decision: dict, *, file_names=None, has_project=False) -> bool:
    decision=decision or {}
    difficulty=int(decision.get("difficulty") or 1)
    caps=decision.get("capabilities") or {}
    req=decision.get("requirement_contract") or {}
    if difficulty>=4:
        return True
    if caps.get("code_fix_loop") or caps.get("world_model") or caps.get("model_competition"):
        return True
    if caps.get("autonomous_research") and difficulty>=3:
        return True
    if bool(has_project) and difficulty>=3:
        return True
    if list(file_names or []) and difficulty>=3:
        return True
    if req.get("density")=="high" and difficulty>=3:
        return True
    return False


def _node(node_id: str, title: str, kind: str, depends=None, proof: str="", meta=None):
    depends=_unique(depends or [])
    return {
        "id":node_id,
        "title":title,
        "kind":kind,
        "depends_on":depends,
        "state":"ready" if not depends else "waiting",
        "proof":proof,
        "detail":"",
        "attempts":0,
        "meta":dict(meta or {}),
    }


def build_task_graph(message: str, decision: dict, *, file_names=None, has_project=False) -> dict[str,Any]:
    decision=decision or {}
    names=[str(x)[:220] for x in (file_names or []) if str(x).strip()][:40]
    active=should_activate(decision,file_names=names,has_project=has_project)
    if not active:
        return {
            "version":VERSION,
            "active":False,
            "revision":0,
            "nodes":[],
            "replanned":False,
            "recovery_attempted":False,
            "dead_end":False,
            "next_actions":[],
            "completion_proof":{},
        }

    caps=decision.get("capabilities") or {}
    req=decision.get("requirement_contract") or {}
    nodes=[]
    nodes.append(_node(
        "understand","Lock the user goal and current scope","understand",
        proof="request parsed into the R23 decision",
        meta={"profile":decision.get("profile"),"difficulty":int(decision.get("difficulty") or 1)},
    ))
    anchor="understand"

    if int(req.get("count") or 0)>0:
        nodes.append(_node(
            "requirements","Freeze explicit must/don't/exactly/preserve constraints","requirements",
            [anchor],
            proof="Requirement Contract is present",
            meta={"count":int(req.get("count") or 0),"hard_count":int(req.get("hard_count") or 0)},
        ))
        anchor="requirements"

    if names or has_project:
        nodes.append(_node(
            "inspect_context","Inspect the attached/project context before changing anything","inspect",
            [anchor],
            proof="project/file context is available to the task",
            meta={"files":names[:20],"has_project":bool(has_project)},
        ))
        anchor="inspect_context"

    evidence_nodes=[]
    if decision.get("needs_live"):
        nodes.append(_node(
            "gather_evidence","Gather current/source evidence required by the task","research",
            [anchor],
            proof="read-page or structured live evidence is present",
        ))
        evidence_nodes.append("gather_evidence")

    if caps.get("world_model"):
        deps=[anchor]
        nodes.append(_node(
            "map_dependencies","Build the dependency/change-impact model","world_model",
            deps,
            proof="static dependency/world model was computed",
        ))
        evidence_nodes.append("map_dependencies")

    if caps.get("code_fix_loop"):
        deps=[anchor]
        if any(x["id"]=="map_dependencies" for x in nodes):
            deps.append("map_dependencies")
        nodes.append(_node(
            "execute_verify","Run code -> test -> fix -> retest","runtime",
            deps,
            proof="controlled runtime reports verified success",
        ))
        evidence_nodes.append("execute_verify")

    if caps.get("computer_requested"):
        nodes.append(_node(
            "observe_computer","Observe the connected computer state through the verified runtime","computer",
            [anchor],
            proof="connected computer observation is explicitly verified",
        ))
        evidence_nodes.append("observe_computer")

    reason_deps=_unique(([anchor] if anchor else [])+evidence_nodes)
    nodes.append(_node(
        "solve","Produce the solution from the gathered context/evidence","reason",
        reason_deps,
        proof="selected main brain has enough supported inputs to synthesize",
    ))

    if decision.get("verify") or evidence_nodes:
        verify_deps=["solve"]+evidence_nodes
        nodes.append(_node(
            "verify","Check requirements, evidence boundaries, and completion claims","verify",
            _unique(verify_deps),
            proof="required evidence/verification gates are satisfied or limitations are explicit",
        ))
        final_dep="verify"
    else:
        final_dep="solve"

    nodes.append(_node(
        "synthesize","Return one final answer without redoing completed work","synthesize",
        [final_dep],
        proof="final answer satisfies the Requirement Contract and evidence boundary",
    ))

    nodes=nodes[:MAX_NODES]
    graph={
        "version":VERSION,
        "active":True,
        "revision":0,
        "goal":str(message or "")[:700],
        "nodes":nodes,
        "replanned":False,
        "replan_reason":"",
        "recovery_kind":"",
        "recovery_attempted":False,
        "dead_end":False,
        "dead_end_reason":"",
        "next_actions":["understand"],
        "completed_nodes":[],
        "failed_nodes":[],
        "blocked_nodes":[],
        "completion_proof":{},
    }
    _refresh_states(graph)
    return graph


def _index(graph):
    return {str(x.get("id")):x for x in (graph.get("nodes") or [])}


def _deps_complete(node, rows):
    return all((rows.get(dep) or {}).get("state")=="complete" for dep in (node.get("depends_on") or []))


def _refresh_states(graph):
    rows=_index(graph)
    changed=True
    while changed:
        changed=False
        for node in graph.get("nodes") or []:
            if node.get("state") in {"complete","failed"}:
                continue
            # Dependency-blocked downstream nodes can become runnable again after
            # a successful recovery pass. Explicit dead-end blocks remain terminal.
            if node.get("state")=="blocked" and node.get("detail")!="dependency did not complete":
                continue
            deps=node.get("depends_on") or []
            dep_rows=[rows.get(x) or {} for x in deps]
            if any(x.get("state") in {"failed","blocked"} for x in dep_rows):
                if node.get("state")!="blocked":
                    node["state"]="blocked"
                    node["detail"]="dependency did not complete"
                    changed=True
            elif _deps_complete(node,rows):
                if node.get("state")!="ready":
                    node["state"]="ready"
                    changed=True
            else:
                node["state"]="waiting"

    graph["completed_nodes"]=[x["id"] for x in graph.get("nodes") or [] if x.get("state")=="complete"]
    graph["failed_nodes"]=[x["id"] for x in graph.get("nodes") or [] if x.get("state")=="failed"]
    graph["blocked_nodes"]=[x["id"] for x in graph.get("nodes") or [] if x.get("state")=="blocked"]
    graph["next_actions"]=[
        x["id"] for x in graph.get("nodes") or []
        if x.get("state")=="ready" and x.get("kind") not in {"understand","requirements","inspect"}
    ][:4]
    required=[x for x in graph.get("nodes") or [] if x.get("kind") in {"research","world_model","runtime","computer","verify","synthesize"}]
    graph["completion_proof"]={
        "required":[{"id":x.get("id"),"proof":x.get("proof"),"state":x.get("state")} for x in required],
        "proved":all(x.get("state")=="complete" for x in required if x.get("kind")!="synthesize") if required else True,
        "unresolved":[x.get("id") for x in required if x.get("state") in {"failed","blocked","waiting"}],
    }
    return graph


def _mark(graph, node_id: str, state: str, detail: str="", attempts_inc: bool=False):
    row=_index(graph).get(node_id)
    if not row:
        return
    row["state"]=state
    row["detail"]=str(detail or "")[:260]
    if attempts_inc:
        row["attempts"]=int(row.get("attempts") or 0)+1


def reconcile_task_graph(graph: dict, tool_run: dict, decision: dict) -> dict[str,Any]:
    graph=copy.deepcopy(graph or {})
    if not graph.get("active"):
        return graph
    tool_run=tool_run or {}
    decision=decision or {}
    executed=set(str(x) for x in (tool_run.get("executed") or []))
    suff=tool_run.get("evidence_sufficiency") or {}
    contract=tool_run.get("evidence_contract") or {}
    gaps=set(str(x) for x in (suff.get("gaps") or []))

    _mark(graph,"understand","complete","request accepted and decomposed")
    if "requirements" in _index(graph):
        _mark(graph,"requirements","complete","explicit current-turn constraints frozen")
    if "inspect_context" in _index(graph):
        _mark(graph,"inspect_context","complete","project/file context admitted to the task graph")

    if "gather_evidence" in _index(graph):
        retrieval=contract.get("retrieval") or {}
        live_ok=bool(
            contract.get("structured_live_data")
            or int(retrieval.get("read_page_count") or 0)>0
            or int(retrieval.get("explicit_browser_pages_read") or 0)>0
        )
        if live_ok and "live_source_evidence" not in gaps and "explicit_url_read" not in gaps:
            _mark(graph,"gather_evidence","complete","live/source evidence retrieved",True)
        elif decision.get("needs_live"):
            _mark(graph,"gather_evidence","failed","required live/source evidence is still missing",True)

    if "map_dependencies" in _index(graph):
        if "world_model" in executed and bool(tool_run.get("world_model")):
            _mark(graph,"map_dependencies","complete","dependency/world model computed",True)
        else:
            _mark(graph,"map_dependencies","failed","dependency/world model did not complete",True)

    if "execute_verify" in _index(graph):
        runtime=contract.get("runtime_execution") or {}
        code=tool_run.get("code_loop") or {}
        verified=bool(runtime.get("verified_success"))
        if verified:
            _mark(graph,"execute_verify","complete","controlled runtime verified success",True)
        elif code or "code_test_fix_retest" in (tool_run.get("planned") or []):
            detail="runtime ran but verified success was not established"
            if code.get("ok"):
                detail="runtime reported success but verification proof is incomplete"
            _mark(graph,"execute_verify","failed",detail,True)

    if "observe_computer" in _index(graph):
        if contract.get("computer_observation_verified"):
            _mark(graph,"observe_computer","complete","connected computer observation verified",True)
        elif "computer_runtime" in (tool_run.get("planned") or []) or "computer_observation" in gaps:
            _mark(graph,"observe_computer","failed","connected computer observation was not verified",True)

    # If this is the bounded recovery pass, close the recovery node according
    # to whether its original failed branch was actually repaired.
    if graph.get("recovery_attempted") and graph.get("recovery_kind"):
        rid="recover_"+str(graph.get("recovery_kind"))
        target=str(graph.get("recovery_target") or "")
        target_row=_index(graph).get(target) or {}
        if target_row.get("state")=="complete":
            _mark(graph,rid,"complete","bounded recovery repaired the target branch",True)
        elif target_row.get("state")=="failed":
            _mark(graph,rid,"failed","bounded recovery did not repair the target branch",True)

    # The main brain has not synthesized yet, but it can proceed once all tool
    # prerequisites are complete or explicitly bounded by a dead-end limitation.
    _refresh_states(graph)
    solve=_index(graph).get("solve")
    if solve and solve.get("state")=="ready":
        solve["detail"]="all currently provable prerequisites are ready for synthesis"

    verify=_index(graph).get("verify")
    if verify and suff:
        if suff.get("sufficient"):
            # Verification of tool evidence is already complete; the main brain
            # still checks the final prose/requirements during synthesis.
            if solve and solve.get("state")=="ready":
                solve["state"]="complete"
                solve["detail"]="supported solution inputs assembled"
            _refresh_states(graph)
            if verify.get("state")=="ready":
                verify["state"]="complete"
                verify["detail"]="mechanical evidence sufficiency gate passed"
        else:
            if solve and solve.get("state")=="ready":
                solve["state"]="complete"
                solve["detail"]="best supported solution assembled with known evidence gaps"
            _refresh_states(graph)
            if verify.get("state")=="ready":
                verify["state"]="failed"
                verify["detail"]="missing evidence: "+", ".join(sorted(gaps))[:200]

    _refresh_states(graph)
    return replan_task_graph(graph,tool_run,decision)


def replan_task_graph(graph: dict, tool_run: dict, decision: dict) -> dict[str,Any]:
    graph=copy.deepcopy(graph or {})
    if not graph.get("active") or graph.get("recovery_attempted"):
        return _refresh_states(graph)

    rows=_index(graph)
    failed=[x for x in graph.get("nodes") or [] if x.get("state")=="failed"]
    if not failed:
        return _refresh_states(graph)

    suff=tool_run.get("evidence_sufficiency") or {}
    gaps=set(str(x) for x in (suff.get("gaps") or []))
    recovery_kind=""
    target=""
    title=""
    proof=""
    deps=[]

    if "live_source_evidence" in gaps or "explicit_url_read" in gaps or (rows.get("gather_evidence") or {}).get("state")=="failed":
        recovery_kind="research"
        target="gather_evidence"
        title="Retry only the missing evidence branch with deeper retrieval"
        proof="fresh readable source evidence is obtained on the bounded recovery pass"
        deps=[x for x in ("requirements","inspect_context","understand") if (rows.get(x) or {}).get("state")=="complete"][-1:]
    elif "runtime_verification" in gaps or (rows.get("execute_verify") or {}).get("state")=="failed":
        recovery_kind="runtime"
        target="execute_verify"
        title="Retry only the failed runtime verification branch"
        proof="controlled retest establishes verified success, otherwise preserve the failure boundary"
        deps=[x for x in ("map_dependencies","inspect_context","requirements","understand") if (rows.get(x) or {}).get("state")=="complete"][-1:]
    elif "static_dependency_analysis" in gaps or (rows.get("map_dependencies") or {}).get("state")=="failed":
        recovery_kind="world_model"
        target="map_dependencies"
        title="Rebuild only the missing dependency-analysis branch"
        proof="static dependency/world model is computed on the bounded recovery pass"
        deps=[x for x in ("inspect_context","requirements","understand") if (rows.get(x) or {}).get("state")=="complete"][-1:]
    elif "computer_observation" in gaps:
        graph["dead_end"]=True
        graph["dead_end_reason"]="connected computer observation is unavailable; no safe local recovery can manufacture that evidence"
        graph["replanned"]=True
        graph["replan_reason"]="unrecoverable_external_capability"
        return _refresh_states(graph)
    else:
        graph["dead_end"]=True
        graph["dead_end_reason"]="a failed branch has no distinct safe recovery path"
        graph["replanned"]=True
        graph["replan_reason"]="no_distinct_recovery"
        return _refresh_states(graph)

    recovery_id="recover_"+recovery_kind
    if recovery_id not in rows and len(graph.get("nodes") or [])<MAX_NODES:
        graph["nodes"].append(_node(
            recovery_id,title,"recovery",deps,proof,
            meta={"target":target,"recovery_kind":recovery_kind},
        ))
    graph["revision"]=int(graph.get("revision") or 0)+1
    graph["replanned"]=True
    graph["replan_reason"]="failed_branch_replanned_without_redoing_completed_nodes"
    graph["recovery_kind"]=recovery_kind
    graph["recovery_target"]=target
    _refresh_states(graph)
    return graph


def recovery_decision(graph: dict, decision: dict, *, has_files=False) -> dict | None:
    graph=graph or {}
    if not graph.get("active") or not graph.get("replanned") or graph.get("dead_end") or graph.get("recovery_attempted"):
        return None
    kind=str(graph.get("recovery_kind") or "")
    if kind not in {"research","runtime","world_model"}:
        return None

    out=copy.deepcopy(decision or {})
    out["task_graph_recovery"]=True
    out["task_graph_revision"]=int(graph.get("revision") or 0)
    out["second_pass"]=False
    out["use_council"]=False
    caps={"agent_runtime":True}

    if kind=="research":
        out["needs_live"]=True
        out["needs_tools"]=True
        out["verify"]=True
        out["depth"]="apex"
        caps.update({
            "universal_retrieval":True,
            "autonomous_research":True,
            "retrieval":copy.deepcopy(((decision or {}).get("capabilities") or {}).get("retrieval") or {}),
        })
    elif kind=="runtime" and has_files:
        out["needs_live"]=False
        out["needs_tools"]=True
        out["verify"]=True
        out["depth"]="deep"
        caps["code_fix_loop"]=True
    elif kind=="world_model" and has_files:
        out["needs_live"]=False
        out["needs_tools"]=True
        out["verify"]=True
        out["depth"]="deep"
        caps["world_model"]=True
    else:
        return None

    out["capabilities"]=caps
    return out


def mark_recovery_attempted(graph: dict) -> dict:
    graph=copy.deepcopy(graph or {})
    if graph.get("active"):
        graph["recovery_attempted"]=True
    return graph


def merge_tool_runs(primary: dict, recovery: dict) -> dict[str,Any]:
    primary=copy.deepcopy(primary or {})
    recovery=copy.deepcopy(recovery or {})
    out=primary
    for key in ("planned","executed","errors"):
        out[key]=_unique(list(primary.get(key) or [])+list(recovery.get(key) or []))

    sources=[]
    seen=set()
    for item in list(primary.get("sources") or [])+list(recovery.get("sources") or []):
        marker=str(item)
        if marker not in seen:
            seen.add(marker)
            sources.append(item)
    out["sources"]=sources[:24]

    evidences=[str(primary.get("evidence") or "").strip(),str(recovery.get("evidence") or "").strip()]
    out["evidence"]="\n\n".join(x for x in evidences if x)[:150000]

    for key in ("browser_pages","world_model","simulation","computer","learning"):
        if recovery.get(key):
            out[key]=recovery.get(key)
        elif key not in out:
            out[key]=primary.get(key) or ([] if key=="browser_pages" else {})

    def research_quality(row):
        row=row or {}
        return (int(row.get("read_count") or 0),int(row.get("source_count") or 0),bool(row.get("ok")))
    out["research"]=recovery.get("research") if research_quality(recovery.get("research"))>research_quality(primary.get("research")) else primary.get("research") or {}

    pcode=primary.get("code_loop") or {}
    rcode=recovery.get("code_loop") or {}
    def code_quality(row):
        return (
            bool(row.get("verified") or (row.get("autofix") or {}).get("verified") or (row.get("autofix") or {}).get("runtime_verified") or (row.get("autofix") or {}).get("final_verified")),
            bool(row.get("ok")),
        )
    out["code_loop"]=rcode if code_quality(rcode)>code_quality(pcode) else pcode

    rec=dict(primary.get("recovery") or {})
    rec.update(recovery.get("recovery") or {})
    rec["task_graph_pass"]={"attempted":True}
    out["recovery"]=rec
    return out


def directive_text(graph: dict) -> str:
    graph=graph or {}
    if not graph.get("active"):
        return ""
    rows=[]
    for node in (graph.get("nodes") or [])[:MAX_NODES]:
        state=str(node.get("state") or "waiting").upper()
        rows.append(
            f"- [{state}] {node.get('id')}: {node.get('title')}"
            + (f" | proof: {node.get('proof')}" if node.get("proof") else "")
        )
    tail=[]
    if graph.get("replanned"):
        tail.append(
            "A failed branch was replanned. Preserve completed nodes and retry only the recovery branch; do not restart the whole task."
        )
    if graph.get("dead_end"):
        tail.append(
            "A real capability/evidence dead-end remains. State that limitation precisely instead of pretending completion."
        )
    tail.append(
        "Before finalizing, satisfy every applicable Requirement Contract item and never mark a proof complete without matching tool/evidence support."
    )
    return (
        "RONN TASK GRAPH (private execution control; do not expose unless the user asks):\n"
        f"Revision: {int(graph.get('revision') or 0)}\n"
        + "\n".join(rows)
        + "\n"
        + "\n".join("- "+x for x in tail)
    )


def status() -> dict[str,Any]:
    return {
        "version":VERSION,
        "enabled":True,
        "selective_activation":True,
        "simple_turns_skipped":True,
        "dependency_tracking":True,
        "bounded_replanning":True,
        "max_recovery_passes":1,
        "preserves_completed_nodes":True,
        "dead_end_detection":True,
        "completion_proofs":True,
        "max_nodes":MAX_NODES,
    }
