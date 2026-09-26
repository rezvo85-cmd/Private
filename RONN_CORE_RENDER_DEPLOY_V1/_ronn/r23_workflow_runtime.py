"""R23 workflow execution adapter with optional LangGraph state management.

R23 Task Graph remains the plan of record. LangGraph is only an execution engine
for already-approved complex tool workflows; it never selects models, changes
R23 requirements, or owns final synthesis.
"""
from __future__ import annotations

import os
from importlib.util import find_spec
from typing import Any, Callable, TypedDict

from r23_agent_runtime import (
    execute as _default_execute,
    evidence_contract as _evidence_contract,
    evidence_sufficiency as _evidence_sufficiency,
)
from r23_task_graph import (
    reconcile_task_graph as _reconcile,
    recovery_decision as _recovery_decision,
    mark_recovery_attempted as _mark_recovery_attempted,
    merge_tool_runs as _merge_tool_runs,
)

VERSION = "R23-WORKFLOW-RUNTIME-3"
_LANGGRAPH_ENABLED = os.getenv("RONN_LANGGRAPH_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


class _LangGraphFailure(RuntimeError):
    """Carries enough state to avoid blindly repeating already-started tools."""

    def __init__(self, error_name: str, *, execution_started=False, tool_run=None, task_graph=None):
        super().__init__(error_name)
        self.error_name = str(error_name or "LangGraphError")
        self.execution_started = bool(execution_started)
        self.tool_run = tool_run
        self.task_graph = task_graph


def langgraph_available() -> bool:
    return bool(_LANGGRAPH_ENABLED and find_spec("langgraph") is not None)


def eligible(decision: dict[str, Any]) -> bool:
    """Only hard, real-tool R23 jobs earn the LangGraph runtime."""
    decision = decision or {}
    graph = decision.get("task_graph") or {}
    caps = decision.get("capabilities") or {}
    difficulty = int(decision.get("difficulty") or 1)
    nodes = list(graph.get("nodes") or [])

    real_complex_work = any(
        caps.get(key)
        for key in (
            "code_fix_loop",
            "world_model",
            "autonomous_research",
            "computer_requested",
            "roblox_studio",
        )
    )
    return bool(
        langgraph_available()
        and graph.get("active")
        and difficulty >= 5
        and len(nodes) >= 6
        and caps.get("agent_runtime")
        and real_complex_work
    )


def _invoke_executor(
    executor: Callable,
    owner: str,
    request_id: str,
    message: str,
    files,
    decision: dict[str, Any],
    repair_fn,
    studio_fn=None,
    studio_checkpoint_fn=None,
) -> dict[str, Any]:
    kwargs={
        "depth":str(decision.get("depth") or "smart"),
        "repair_fn":repair_fn,
    }
    # Keep test/custom executors backward compatible: Studio-only kwargs are
    # supplied only when the application actually configured the Studio agent.
    if studio_fn is not None:
        kwargs["studio_fn"]=studio_fn
    if studio_checkpoint_fn is not None:
        kwargs["studio_checkpoint_fn"]=studio_checkpoint_fn
    return executor(
        owner,
        request_id,
        message,
        files or [],
        decision,
        **kwargs,
    )


def _merge_after_recovery(
    graph: dict[str, Any],
    primary: dict[str, Any],
    recovery: dict[str, Any],
    original_decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = _merge_tool_runs(primary, recovery)
    contract = _evidence_contract(merged)
    sufficiency = _evidence_sufficiency(
        merged,
        original_decision,
        contract=contract,
        depth=str(original_decision.get("depth") or "smart"),
    )
    contract["sufficiency"] = sufficiency
    merged["evidence_contract"] = contract
    merged["evidence_sufficiency"] = sufficiency
    graph = _reconcile(graph, merged, original_decision)
    return graph, merged


def _direct(
    owner: str,
    request_id: str,
    message: str,
    files,
    decision: dict[str, Any],
    repair_fn,
    executor: Callable,
    checkpoint_fn: Callable | None,
    studio_fn=None,
    studio_checkpoint_fn=None,
) -> dict[str, Any]:
    tool_run = _invoke_executor(
        executor, owner, request_id, message, files, decision, repair_fn,
        studio_fn, studio_checkpoint_fn,
    )
    graph = _reconcile(decision.get("task_graph") or {}, tool_run, decision)
    recovery = _recovery_decision(graph, decision, has_files=bool(files))

    if recovery:
        graph = _mark_recovery_attempted(graph)
        if checkpoint_fn:
            try:
                checkpoint_fn(request_id, "Replan", "started", "Retrying only the failed R23 task-graph branch.")
            except Exception:
                pass
        try:
            recovery_run = _invoke_executor(
                executor, owner, request_id + "_replan", message, files, recovery, repair_fn,
                studio_fn, studio_checkpoint_fn,
            )
            graph, tool_run = _merge_after_recovery(graph, tool_run, recovery_run, decision)
            if checkpoint_fn:
                try:
                    ok = bool((tool_run.get("evidence_sufficiency") or {}).get("sufficient"))
                    checkpoint_fn(
                        request_id,
                        "Replan",
                        "complete" if ok else "blocked",
                        "Bounded R23 failed-branch recovery completed.",
                    )
                except Exception:
                    pass
        except Exception as exc:
            tool_run.setdefault("errors", []).append("task_graph_recovery:" + exc.__class__.__name__)
            graph = _reconcile(graph, tool_run, decision)

    return {
        "engine": "direct",
        "used_langgraph": False,
        "tool_run": tool_run,
        "task_graph": graph,
    }


class _WorkflowState(TypedDict, total=False):
    owner: str
    request_id: str
    message: str
    files: Any
    decision: dict[str, Any]
    repair_fn: Any
    executor: Any
    checkpoint_fn: Any
    studio_fn: Any
    studio_checkpoint_fn: Any
    tool_run: dict[str, Any]
    task_graph: dict[str, Any]
    recovery_decision: dict[str, Any] | None
    recovery_run: dict[str, Any]
    errors: list[str]


def _langgraph_run(
    owner: str,
    request_id: str,
    message: str,
    files,
    decision: dict[str, Any],
    repair_fn,
    executor: Callable,
    checkpoint_fn: Callable | None,
    studio_fn=None,
    studio_checkpoint_fn=None,
) -> dict[str, Any]:
    progress = {
        "execution_started": False,
        "tool_run": None,
        "task_graph": decision.get("task_graph") or {},
    }
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as exc:
        raise _LangGraphFailure(exc.__class__.__name__) from exc

    def execute_node(state: _WorkflowState):
        progress["execution_started"] = True
        run = _invoke_executor(
            state["executor"],
            state["owner"],
            state["request_id"],
            state["message"],
            state.get("files") or [],
            state["decision"],
            state.get("repair_fn"),
            state.get("studio_fn"),
            state.get("studio_checkpoint_fn"),
        )
        progress["tool_run"] = run
        return {"tool_run": run}

    def reconcile_node(state: _WorkflowState):
        graph = _reconcile(
            state["decision"].get("task_graph") or {},
            state.get("tool_run") or {},
            state["decision"],
        )
        progress["task_graph"] = graph
        recovery = _recovery_decision(
            graph,
            state["decision"],
            has_files=bool(state.get("files")),
        )
        return {"task_graph": graph, "recovery_decision": recovery}

    def route_after_reconcile(state: _WorkflowState):
        return "recover" if state.get("recovery_decision") else "finish"

    def recover_node(state: _WorkflowState):
        recovery = state.get("recovery_decision")
        if not recovery:
            return {}
        graph = _mark_recovery_attempted(state.get("task_graph") or {})
        checkpoint = state.get("checkpoint_fn")
        if checkpoint:
            try:
                checkpoint(state["request_id"], "Replan", "started", "LangGraph is executing the single R23-approved recovery branch.")
            except Exception:
                pass
        try:
            recovery_run = _invoke_executor(
                state["executor"],
                state["owner"],
                state["request_id"] + "_replan",
                state["message"],
                state.get("files") or [],
                recovery,
                state.get("repair_fn"),
            )
            graph, merged = _merge_after_recovery(
                graph,
                state.get("tool_run") or {},
                recovery_run,
                state["decision"],
            )
            progress["tool_run"] = merged
            progress["task_graph"] = graph
            if checkpoint:
                try:
                    ok = bool((merged.get("evidence_sufficiency") or {}).get("sufficient"))
                    checkpoint(
                        state["request_id"],
                        "Replan",
                        "complete" if ok else "blocked",
                        "LangGraph completed the bounded R23 recovery branch.",
                    )
                except Exception:
                    pass
            return {
                "task_graph": graph,
                "recovery_run": recovery_run,
                "tool_run": merged,
            }
        except Exception as exc:
            # Never replay the primary action because only the bounded recovery failed.
            primary = dict(state.get("tool_run") or {})
            primary.setdefault("errors", []).append(
                "task_graph_recovery:" + exc.__class__.__name__
            )
            graph = _reconcile(graph, primary, state["decision"])
            progress["tool_run"] = primary
            progress["task_graph"] = graph
            if checkpoint:
                try:
                    checkpoint(
                        state["request_id"],
                        "Replan",
                        "blocked",
                        "Bounded R23 recovery failed without repeating the primary tool action.",
                    )
                except Exception:
                    pass
            return {
                "task_graph": graph,
                "recovery_run": {},
                "tool_run": primary,
            }

    workflow = StateGraph(_WorkflowState)
    workflow.add_node("execute", execute_node)
    workflow.add_node("reconcile", reconcile_node)
    workflow.add_node("recover", recover_node)
    workflow.add_node("finish", lambda state: {})
    workflow.add_edge(START, "execute")
    workflow.add_edge("execute", "reconcile")
    workflow.add_conditional_edges(
        "reconcile",
        route_after_reconcile,
        {"recover": "recover", "finish": "finish"},
    )
    workflow.add_edge("recover", "finish")
    workflow.add_edge("finish", END)

    try:
        compiled = workflow.compile()
    except Exception as exc:
        raise _LangGraphFailure(exc.__class__.__name__) from exc

    try:
        result = compiled.invoke(
            {
                "owner": owner,
                "request_id": request_id,
                "message": message,
                "files": files or [],
                "decision": decision,
                "repair_fn": repair_fn,
                "executor": executor,
                "checkpoint_fn": checkpoint_fn,
                "studio_fn": studio_fn,
                "studio_checkpoint_fn": studio_checkpoint_fn,
                "errors": [],
            }
        )
    except Exception as exc:
        raise _LangGraphFailure(
            exc.__class__.__name__,
            execution_started=progress["execution_started"],
            tool_run=progress["tool_run"],
            task_graph=progress["task_graph"],
        ) from exc
    return {
        "engine": "langgraph",
        "used_langgraph": True,
        "tool_run": result.get("tool_run") or {},
        "task_graph": result.get("task_graph") or decision.get("task_graph") or {},
    }


def run(
    owner: str,
    request_id: str,
    message: str,
    files,
    decision: dict[str, Any],
    *,
    repair_fn=None,
    executor: Callable | None = None,
    checkpoint_fn: Callable | None = None,
    studio_fn=None,
    studio_checkpoint_fn=None,
) -> dict[str, Any]:
    """Execute exactly one workflow engine for this R23 decision."""
    executor = executor or _default_execute

    if eligible(decision):
        try:
            return _langgraph_run(
                owner, request_id, message, files, decision, repair_fn, executor, checkpoint_fn,
                studio_fn, studio_checkpoint_fn,
            )
        except _LangGraphFailure as exc:
            # A direct fallback is safe only before any primary tool execution starts.
            if not exc.execution_started:
                fallback = _direct(
                    owner, request_id, message, files, decision, repair_fn, executor, checkpoint_fn,
                    studio_fn, studio_checkpoint_fn,
                )
                fallback["fallback_from"] = "langgraph"
                fallback["workflow_error"] = exc.error_name
                fallback["tool_run"].setdefault("errors", []).append(
                    "langgraph_pre_execution_fallback:" + exc.error_name
                )
                return fallback

            # Once execution starts, never blindly replay it. Preserve any completed
            # result and let R23 synthesize with the explicit degraded/error state.
            if isinstance(exc.tool_run, dict):
                tool_run = dict(exc.tool_run)
                tool_run.setdefault("errors", []).append(
                    "langgraph_post_execution:" + exc.error_name
                )
                try:
                    graph = exc.task_graph or _reconcile(
                        decision.get("task_graph") or {}, tool_run, decision
                    )
                except Exception:
                    graph = decision.get("task_graph") or {}
                return {
                    "engine": "langgraph_degraded",
                    "used_langgraph": True,
                    "tool_run": tool_run,
                    "task_graph": graph,
                    "fallback_from": "",
                    "workflow_error": exc.error_name,
                }

            return {
                "engine": "langgraph_error",
                "used_langgraph": True,
                "tool_run": {
                    "planned": [],
                    "executed": [],
                    "evidence": "",
                    "sources": [],
                    "errors": ["langgraph_execution_started:" + exc.error_name],
                },
                "task_graph": exc.task_graph or decision.get("task_graph") or {},
                "fallback_from": "",
                "workflow_error": exc.error_name,
            }

    return _direct(
        owner, request_id, message, files, decision, repair_fn, executor, checkpoint_fn,
        studio_fn, studio_checkpoint_fn,
    )


def status() -> dict[str, Any]:
    return {
        "version": VERSION,
        "langgraph_enabled": _LANGGRAPH_ENABLED,
        "langgraph_installed": find_spec("langgraph") is not None,
        "langgraph_available": langgraph_available(),
        "activation": "R23 task graph active + difficulty>=5 + >=6 nodes + real tool work",
        "simple_chat_skipped": True,
        "r23_plan_of_record": True,
        "owns_model_routing": False,
        "owns_final_answer": False,
        "fallback": "direct R23 workflow only before tool execution starts",
        "no_duplicate_action_replay": True,
        "roblox_studio_executor_passthrough": True,
    }
