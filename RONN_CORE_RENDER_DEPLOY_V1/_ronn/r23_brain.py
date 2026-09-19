"""RONN R23 unified brain.

R23 keeps the R22 rule: one main brain owns the answer. The eleven major
capabilities sit underneath it as tools/evidence, not as competing prompt layers.
"""
from __future__ import annotations

from r22_lean_core import plan as r22_plan
from r23_capabilities import capability_plan, status as capability_status

R23_VERSION="R23-UNIFIED-BRAIN-1"


def plan(message, history=None, file_names=None, has_images=False, has_project=False,
         agent_mode=True, explicit_mode="auto"):
    base=r22_plan(
        message,
        history=history or [],
        file_names=file_names or [],
        has_images=has_images,
        has_project=has_project,
        agent_mode=agent_mode,
        explicit_mode=explicit_mode,
    )
    caps=capability_plan(
        base,message,
        history=history or [],
        file_names=file_names or [],
        has_images=has_images,
        has_project=has_project,
        agent_mode=agent_mode,
    )

    out=dict(base)
    out.update({
        "version":R23_VERSION,
        "r23":True,
        "lean_core":True,
        "main_brain_first":True,
        "capabilities":caps,
    })

    retrieval=caps.get("retrieval") or {}
    if caps.get("universal_retrieval"):
        out["needs_live"]=True
        out["needs_tools"]=True
        out["tool_mode"]="live"
        if retrieval.get("unknown_terms") and out.get("profile")=="chat":
            out["profile"]="knowledge"

    # Deep autonomous research earns more synthesis budget, but it still returns
    # to the same main brain for the final answer.
    if caps.get("autonomous_research") and out.get("depth") in {"fast","smart"}:
        out["depth"]="deep"

    # Automatic competition is intentionally rare. It is for genuinely hard work
    # only, so normal conversation stays one-brain and clean.
    out["use_council"]=bool(caps.get("model_competition"))
    if out["use_council"]:
        out["second_pass"]=False

    policy=dict(out.get("prompt_policy") or {})
    if caps.get("long_context"):
        policy["include_long_context_digest"]=True
    if caps.get("project_brain"):
        policy["include_project_graph"]=True
        policy["include_knowledge_base"]=True
    if caps.get("failure_learning") and (out.get("verify") or int(out.get("difficulty") or 1)>=4):
        policy["include_failure_lessons"]=True
    if caps.get("agent_runtime"):
        policy["include_agent_directive"]=True
    if caps.get("universal_retrieval"):
        policy["include_evidence_plan"]=True
    out["prompt_policy"]=policy
    out["reason"]="R23 unified main brain with selective 11-capability runtime"
    return out


def resolve_route(decision,providers,models):
    """Select the strongest available main brain.

    Research and code execution happen beneath this model. We do not replace the
    main thinker with a smaller specialist merely because a tool was used.
    """
    openrouter=bool(providers.get("openrouter"))
    nvidia=bool(providers.get("nvidia"))
    groq=bool(providers.get("groq"))

    if decision.get("specialist")=="vision":
        if openrouter:return models["or_qwen"],"vision"
        return models["vision"],"vision"

    depth=str(decision.get("depth") or "smart")
    if openrouter:
        # Nemotron Ultra 550B is RONN's strongest configured general reasoning
        # brain. DeepSeek/Qwen remain specialists/competitors, not the default mind.
        return models["or_nemotron"],("apex" if depth=="apex" else ("deep" if depth=="deep" else "knowledge"))
    if nvidia:
        return models["nvidia"],("apex" if depth=="apex" else ("deep" if depth=="deep" else "knowledge"))
    if groq:
        return models["smart"],("deep" if depth in {"deep","apex"} else "knowledge")
    return models["smart"],"knowledge"


def directive(decision):
    caps=decision.get("capabilities") or {}
    active=[
        name for name,key in (
            ("agent runtime","agent_runtime"),
            ("code test/fix/retest","code_fix_loop"),
            ("project brain","project_brain"),
            ("long-context compression","long_context"),
            ("model competition","model_competition"),
            ("world model","world_model"),
            ("autonomous research","autonomous_research"),
            ("universal retrieval","universal_retrieval"),
        ) if caps.get(key)
    ]
    return (
        "RONN R23 UNIFIED BRAIN:\n"
        "- One strongest available main brain owns the final answer.\n"
        "- Tools, memory, research, execution, simulation, and specialist models support that brain; they do not compete with its instructions.\n"
        f"- Reasoning depth: {decision.get('depth')}\n"
        f"- Task profile: {decision.get('profile')}\n"
        f"- Active capabilities: {', '.join(active) if active else 'main brain only'}\n"
        "- Use real tool evidence when present. Never claim an action succeeded without evidence.\n"
        "- Keep simple answers simple; use the larger capability plane only when the task earns it."
    )


def status():
    caps=capability_status()
    return {
        "version":R23_VERSION,
        "central_controller":True,
        "lean_core":True,
        "main_brain_first":True,
        "feature_count":caps.get("feature_count",0),
        "features":caps.get("features",{}),
        "policy":"strongest-main-brain + selective capability plane",
        "council_default":False,
        "competition_threshold":"difficulty>=6 only",
    }
