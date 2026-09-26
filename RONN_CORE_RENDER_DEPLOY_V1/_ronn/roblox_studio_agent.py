"""Bounded R23-owned Roblox Studio development loop.

The Studio MCP server is an execution/observation tool, not another RONN brain.
The already-selected R23 main model plans small batches against the live tool
schemas, while this module enforces tool allowlists, exact Studio targeting,
bounded retries, evidence capture, and playtest verification.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import roblox_studio_gateway as studio

VERSION = "RONN-R23-ROBLOX-STUDIO-AGENT-2"
MAX_INSPECT_CALLS = 7
MAX_EDIT_CALLS = 7
MAX_VERIFY_CALLS = 6
MAX_REPAIR_PASSES = 2

INSPECT_TOOLS = {
    "script_read",
    "script_search",
    "script_grep",
    "search_game_tree",
    "inspect_instance",
    "get_studio_state",
    "get_console_output",
    "screen_capture",
    "skill",
}
EDIT_TOOLS = {
    "multi_edit",
    "execute_luau",
    "search_asset",
    "insert_asset",
    "generate_mesh",
    "generate_material",
    "generate_procedural_model",
    "wait_job_finished",
}
VERIFY_TOOLS = {
    "start_stop_play",
    "get_console_output",
    "screen_capture",
    "subagent",
    "get_studio_state",
    "inspect_instance",
    "script_read",
    "script_grep",
    "character_navigation",
    "user_keyboard_input",
    "user_mouse_input",
}

_MUTATION_WORDS = (
    "fix", "repair", "build", "make", "create", "add", "implement", "change",
    "edit", "update", "replace", "remove", "delete", "insert", "rewrite",
    "restore", "wire", "connect", "set up", "setup", "put in", "modify",
)
_VERIFY_WORDS = (
    "test", "playtest", "verify", "make sure", "check everything", "check it",
    "no bugs", "works", "working", "retest",
)


def _clip(value: Any, limit: int = 18000) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
    return text[:limit]


def _json_object(text: str) -> dict[str, Any]:
    raw = re.sub(r"(?is)<think>.*?</think>|</?think>", "", str(text or "")).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Studio planner did not return a JSON object.")
    return value


def _call_model(model_fn: Callable, system: str, user: str, max_tokens: int = 1500) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    result = model_fn(messages, max_tokens)
    if isinstance(result, tuple):
        result = result[0]
    return _json_object(str(result or ""))


def _schemas(catalog: list[dict[str, Any]], names: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "name": row.get("name"),
            "description": row.get("description"),
            "inputSchema": row.get("inputSchema") or {},
        }
        for row in catalog
        if row.get("name") in names
    ]


def _clean_calls(raw: Any, allowed: set[str], max_calls: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:max_calls]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        args = item.get("arguments")
        if name not in allowed or not isinstance(args, dict):
            continue
        args = dict(args)
        # Exact Studio targeting is injected by the gateway.
        args.pop("studio_id", None)
        args.pop("studioId", None)
        out.append({"name": name, "arguments": args})
    return out


def _run_calls(
    owner: str,
    target: dict[str, Any],
    calls: list[dict[str, Any]],
    *,
    phase: str,
    timeout: float = 55.0,
    checkpoint_fn=None,
) -> list[dict[str, Any]]:
    out = []
    total = len(calls)
    for index, call in enumerate(calls, start=1):
        name = call["name"]
        if checkpoint_fn:
            try:
                checkpoint_fn(
                    "Studio " + phase,
                    "started",
                    f"{name} ({index}/{total})",
                )
            except Exception:
                pass
        try:
            result = studio.call_tool(
                owner,
                name,
                call["arguments"],
                bridge_id=target["bridge_id"],
                studio_id=target["studio_id"],
                timeout=timeout,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "tool": name,
                "reason": exc.__class__.__name__,
                "error": str(exc)[:500],
            }
        out.append({
            "phase": phase,
            "name": name,
            "arguments": call["arguments"],
            "ok": bool(result.get("ok")),
            "result": result,
        })
        if checkpoint_fn:
            try:
                checkpoint_fn(
                    "Studio " + phase,
                    "complete" if result.get("ok") else "blocked",
                    f"{name}: " + ("ok" if result.get("ok") else str(result.get("reason") or result.get("error") or "failed"))[:220],
                )
            except Exception:
                pass
    return out


def _mutating_request(message: str) -> bool:
    low = re.sub(r"\s+", " ", str(message or "")).lower()
    return any(word in low for word in _MUTATION_WORDS)


def _verification_requested(message: str) -> bool:
    low = re.sub(r"\s+", " ", str(message or "")).lower()
    return _mutating_request(message) or any(word in low for word in _VERIFY_WORDS)


def _planner_system(phase: str, allowed: set[str]) -> str:
    return f"""You are the Roblox Studio execution planner inside RONN R23.
R23 remains the single main brain. Produce only a compact JSON tool plan for phase {phase}.

Hard rules:
- Use ONLY tools in this phase allowlist: {sorted(allowed)}.
- Arguments MUST follow the supplied LIVE MCP inputSchema exactly.
- OMIT studio_id from your arguments; RONN injects the already-verified exact Studio instance id.
- Never invent paths, script names, instances, assets, IDs, or tool arguments. Inspect first when uncertain.
- Preserve existing systems and naming. Do not replace unrelated architecture.
- Prefer the smallest complete change that solves the user's actual request.
- Never use execute_luau for filesystem/OS/network activity. It is only for the selected Roblox Studio DataModel/test state.
- For edits, prefer multi_edit for known scripts. Use execute_luau only when a DataModel mutation cannot be expressed safely otherwise.
- Do not publish, purchase, spend currency, change account/security settings, or access secrets.
- Return JSON only.

Schema:
{{"summary":"short","calls":[{{"name":"tool_name","arguments":{{}}}}]}}
"""


def _inspection_plan(model_fn, message: str, target, catalog, state_evidence) -> list[dict[str, Any]]:
    allowed = INSPECT_TOOLS & {x.get("name") for x in catalog}
    if not allowed:
        return []
    plan = _call_model(
        model_fn,
        _planner_system("inspection", allowed),
        "USER REQUEST:\n"
        + message[:9000]
        + "\n\nSELECTED STUDIO:\n"
        + _clip(target, 3000)
        + "\n\nLIVE TOOL SCHEMAS:\n"
        + _clip(_schemas(catalog, allowed), 26000)
        + "\n\nINITIAL STUDIO STATE EVIDENCE:\n"
        + _clip(state_evidence, 14000)
        + "\n\nPlan only the reads needed to understand the exact existing implementation before changing anything.",
        1500,
    )
    return _clean_calls(plan.get("calls"), allowed, MAX_INSPECT_CALLS)


def _edit_plan(model_fn, message: str, target, catalog, evidence, repair_context: str = "") -> list[dict[str, Any]]:
    allowed = EDIT_TOOLS & {x.get("name") for x in catalog}
    if not allowed:
        return []
    system = _planner_system("repair" if repair_context else "edit", allowed)
    system += """
For code changes, keep every referenced RemoteEvent/ModuleScript/function/path internally consistent.
Do not claim a runtime result in code comments. Avoid broad rewrites when a narrow repair is possible.
"""
    user = (
        "USER REQUEST:\n" + message[:9000]
        + "\n\nSELECTED STUDIO:\n" + _clip(target, 3000)
        + "\n\nLIVE TOOL SCHEMAS:\n" + _clip(_schemas(catalog, allowed), 26000)
        + "\n\nREAL STUDIO INSPECTION/TEST EVIDENCE:\n" + _clip(evidence, 50000)
    )
    if repair_context:
        user += "\n\nFAILED VERIFICATION TO REPAIR:\n" + repair_context[:18000]
    user += "\n\nReturn only the minimum safe mutation calls needed now."
    plan = _call_model(model_fn, system, user, 2400)
    return _clean_calls(plan.get("calls"), allowed, MAX_EDIT_CALLS)


def _verification_plan(model_fn, message: str, target, catalog, evidence) -> dict[str, Any]:
    allowed = VERIFY_TOOLS & {x.get("name") for x in catalog}
    if not allowed:
        return {"calls": [], "cleanup_calls": []}
    system = _planner_system("verification", allowed) + """
Verification must use actual Studio evidence. For gameplay/runtime changes, prefer a real Play test plus get_console_output.
If you start Play mode, include an explicit cleanup_calls entry that stops Play mode even when the test fails.
The subagent tool may be used only in explore/playtest mode as a bounded Studio observer; it never owns RONN's final answer.
Return JSON:
{"summary":"short","calls":[...],"cleanup_calls":[...]}
"""
    plan = _call_model(
        model_fn,
        system,
        "USER REQUEST:\n" + message[:9000]
        + "\n\nSELECTED STUDIO:\n" + _clip(target, 3000)
        + "\n\nLIVE TOOL SCHEMAS:\n" + _clip(_schemas(catalog, allowed), 28000)
        + "\n\nREAL EVIDENCE AFTER EDITS:\n" + _clip(evidence, 52000)
        + "\n\nCreate a bounded test that can actually prove or disprove the requested behavior.",
        1800,
    )
    return {
        "calls": _clean_calls(plan.get("calls"), allowed, MAX_VERIFY_CALLS),
        "cleanup_calls": _clean_calls(plan.get("cleanup_calls"), allowed, 2),
    }


def _assess_verification(model_fn, message: str, evidence) -> dict[str, Any]:
    system = """You are RONN's evidence-only Roblox verification judge.
Do not propose edits and do not invent observations. Decide only whether the REAL Studio evidence proves the user's requested change works.
A clean console alone does not prove gameplay behavior. Runtime gameplay requests need a Play test or playtest subagent evidence.
Return JSON only:
{"passed":true|false,"reason":"short evidence-grounded reason","repairable":true|false}
"""
    try:
        result = _call_model(
            model_fn,
            system,
            "USER REQUEST:\n" + message[:9000] + "\n\nREAL STUDIO EVIDENCE:\n" + _clip(evidence, 60000),
            500,
        )
    except Exception as exc:
        return {"passed": False, "reason": "verification_judge_" + exc.__class__.__name__, "repairable": False}
    return {
        "passed": bool(result.get("passed")),
        "reason": re.sub(r"\s+", " ", str(result.get("reason") or "")).strip()[:500],
        "repairable": bool(result.get("repairable", True)),
    }


def run(
    owner: str,
    message: str,
    *,
    model_fn: Callable | None,
    depth: str = "smart",
    checkpoint_fn=None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": VERSION,
        "ok": False,
        "available": False,
        "modified": False,
        "verification_attempted": False,
        "playtest_verified": False,
        "rollback_ready": False,
        "target": {},
        "calls": [],
        "errors": [],
        "assessment": {},
        "repair_passes": 0,
    }

    status = studio.status(owner)
    result["status"] = status
    if not status.get("online"):
        result["reason"] = "bridge_offline"
        result["setup_required"] = True
        return result

    target_result = studio.resolve_target(owner, message=message)
    if not target_result.get("ok"):
        result["reason"] = target_result.get("reason") or "target_unavailable"
        result["targets"] = target_result.get("studios") or []
        return result

    target = target_result["target"]
    result["available"] = True
    result["target"] = target
    catalog = studio.tool_catalog(owner, target["bridge_id"])
    result["tool_count"] = len(catalog)
    result["tool_names"] = [x.get("name") for x in catalog]

    if model_fn is None:
        result["reason"] = "planner_unavailable"
        return result

    evidence: list[dict[str, Any]] = []

    # Always begin with a real Studio-state observation when the tool exists.
    if "get_studio_state" in result["tool_names"]:
        first = _run_calls(
            owner,
            target,
            [{"name": "get_studio_state", "arguments": {}}],
            phase="state",
            checkpoint_fn=checkpoint_fn,
        )
        evidence.extend(first)
        result["calls"].extend(first)

    try:
        inspect_calls = _inspection_plan(model_fn, message, target, catalog, evidence)
    except Exception as exc:
        inspect_calls = []
        result["errors"].append("inspection_plan:" + exc.__class__.__name__)

    inspected = _run_calls(
        owner,
        target,
        inspect_calls,
        phase="inspect",
        checkpoint_fn=checkpoint_fn,
    )
    evidence.extend(inspected)
    result["calls"].extend(inspected)

    mutate = _mutating_request(message)
    result["mutation_requested"] = mutate
    if not mutate:
        result["ok"] = bool(evidence) and all(x.get("ok") for x in evidence)
        result["reason"] = "inspection_complete"
        result["evidence"] = evidence
        return result

    # The inspection evidence itself is the pre-change checkpoint. script_read
    # calls retain exact source text in the returned MCP result when the planner
    # is about to modify known scripts.
    result["rollback_ready"] = any(
        x.get("name") == "script_read" and x.get("ok")
        for x in evidence
    )

    try:
        edits = _edit_plan(model_fn, message, target, catalog, evidence)
    except Exception as exc:
        result["errors"].append("edit_plan:" + exc.__class__.__name__)
        result["reason"] = "edit_plan_failed"
        result["evidence"] = evidence
        return result

    if not edits:
        result["reason"] = "no_safe_edit_plan"
        result["evidence"] = evidence
        return result

    edit_results = _run_calls(
        owner,
        target,
        edits,
        phase="edit",
        timeout=70.0,
        checkpoint_fn=checkpoint_fn,
    )
    evidence.extend(edit_results)
    result["calls"].extend(edit_results)
    result["modified"] = any(x.get("ok") and x.get("name") in EDIT_TOOLS for x in edit_results)
    edit_uncertain=any(
        bool((x.get("result") or {}).get("uncertain"))
        for x in edit_results
        if isinstance(x,dict)
    )

    if edit_uncertain:
        # Exactly-once delivery cannot be proven after a mutating MCP timeout.
        # Do NOT stack a second repair on top of a change that may already have
        # landed. The next RONN turn begins with a fresh Studio inspection.
        result["reason"] = "mutation_delivery_uncertain"
        result["errors"].append("mutation_delivery_uncertain_no_replay")
        result["evidence"] = evidence
        return result

    if not all(x.get("ok") for x in edit_results):
        result["reason"] = "edit_tool_failed"
        result["errors"].append("one_or_more_edit_calls_failed")

    if not _verification_requested(message):
        result["ok"] = result["modified"] and all(x.get("ok") for x in edit_results)
        result["reason"] = "modified_not_runtime_verified"
        result["evidence"] = evidence
        return result

    # Always verify mutation requests. Repairs are bounded to two passes.
    for repair_index in range(MAX_REPAIR_PASSES + 1):
        try:
            verify_plan = _verification_plan(model_fn, message, target, catalog, evidence)
        except Exception as exc:
            result["errors"].append("verification_plan:" + exc.__class__.__name__)
            break

        verify_calls = verify_plan.get("calls") or []
        cleanup_calls = verify_plan.get("cleanup_calls") or []
        result["verification_attempted"] = result["verification_attempted"] or bool(verify_calls)

        verify_results = []
        try:
            verify_results = _run_calls(
                owner,
                target,
                verify_calls,
                phase="verify",
                timeout=90.0,
                checkpoint_fn=checkpoint_fn,
            )
            evidence.extend(verify_results)
            result["calls"].extend(verify_results)
        finally:
            if cleanup_calls:
                cleanup_results = _run_calls(
                    owner,
                    target,
                    cleanup_calls,
                    phase="cleanup",
                    timeout=30.0,
                    checkpoint_fn=checkpoint_fn,
                )
                evidence.extend(cleanup_results)
                result["calls"].extend(cleanup_results)

        verify_uncertain=any(
            bool((x.get("result") or {}).get("uncertain"))
            for x in verify_results
            if isinstance(x,dict)
        )
        assessment = _assess_verification(model_fn, message, evidence)
        result["assessment"] = assessment

        if verify_uncertain:
            result["reason"] = "verification_delivery_uncertain"
            result["errors"].append("verification_mutation_uncertain_no_repair")
            break

        names = {x.get("name") for x in verify_results if x.get("ok")}
        runtime_observed = bool(
            "subagent" in names
            or "start_stop_play" in names
            or "character_navigation" in names
        )
        console_observed = "get_console_output" in names
        calls_ok = bool(verify_results) and all(x.get("ok") for x in verify_results)
        result["playtest_verified"] = bool(
            assessment.get("passed")
            and calls_ok
            and runtime_observed
            and console_observed
        )

        if result["playtest_verified"]:
            result["ok"] = True
            result["reason"] = "studio_playtest_verified"
            break

        if repair_index >= MAX_REPAIR_PASSES or not assessment.get("repairable"):
            result["reason"] = "verification_not_proven"
            break

        try:
            repairs = _edit_plan(
                model_fn,
                message,
                target,
                catalog,
                evidence,
                repair_context=str(assessment.get("reason") or "Verification did not prove success."),
            )
        except Exception as exc:
            result["errors"].append("repair_plan:" + exc.__class__.__name__)
            break
        if not repairs:
            break

        repair_results = _run_calls(
            owner,
            target,
            repairs,
            phase="repair",
            timeout=70.0,
            checkpoint_fn=checkpoint_fn,
        )
        evidence.extend(repair_results)
        result["calls"].extend(repair_results)
        result["repair_passes"] += 1
        result["modified"] = result["modified"] or any(x.get("ok") for x in repair_results)
        if not all(x.get("ok") for x in repair_results):
            result["errors"].append("repair_tool_failed")
            break

    result["evidence"] = evidence
    return result


def status() -> dict[str, Any]:
    return {
        "version": VERSION,
        "r23_owned": True,
        "owns_model_routing": False,
        "owns_final_answer": False,
        "live_schema_planning": True,
        "exact_studio_targeting": True,
        "max_inspect_calls": MAX_INSPECT_CALLS,
        "max_edit_calls": MAX_EDIT_CALLS,
        "max_verify_calls": MAX_VERIFY_CALLS,
        "max_repair_passes": MAX_REPAIR_PASSES,
        "playtest_evidence_required": True,
        "ambiguous_mutation_auto_replay": False,
    }
