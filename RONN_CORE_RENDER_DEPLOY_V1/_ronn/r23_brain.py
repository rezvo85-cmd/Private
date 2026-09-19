"""RONN R23 unified brain.

R23 keeps the R22 rule: one main brain owns the answer. The eleven major
capabilities sit underneath it as tools/evidence, not as competing prompt layers.
"""
from __future__ import annotations

from r22_lean_core import plan as r22_plan
from r23_capabilities import capability_plan, status as capability_status
from provider_engine import model_penalty
from experience_engine import model_feedback_penalty
from r23_brain_arena import routing_signal as arena_routing_signal

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


def _main_brain_candidates(providers,models):
    """Quality-first primary-brain order, filtered to configured providers."""
    out=[]
    if providers.get("openrouter") and models.get("or_nemotron"):
        out.append((models["or_nemotron"],"openrouter",0))
    if providers.get("nvidia") and models.get("nvidia"):
        out.append((models["nvidia"],"nvidia",1))
    if providers.get("groq") and models.get("smart"):
        out.append((models["smart"],"groq",2))
    return out


def _pick_main_brain(providers,models):
    """Pick the strongest healthy configured brain.

    Default quality order is Nemotron Ultra -> NVIDIA Nemotron -> GPT-OSS 120B.
    Repeated provider failures or multiple negative user ratings can temporarily
    demote a model so RONN does not keep paying a failed first-attempt penalty.
    """
    candidates=_main_brain_candidates(providers,models)
    if not candidates:
        return models["smart"],"unknown",0

    arena=arena_routing_signal([m for m,_,_ in candidates])
    arena_ready=bool(arena.get("ready"))
    arena_scores=arena.get("scores") or {}

    scored=[]
    for model,provider,quality_rank in candidates:
        health=int(model_penalty(model) or 0)
        feedback=int(model_feedback_penalty(model) or 0)
        row=arena_scores.get(model) or {}
        arena_score=float(row.get("score") or 0)
        arena_latency=float(row.get("latency") or 999)
        # Reliability and repeated user feedback remain the strongest guardrails.
        # When every candidate has enough fresh objective samples, arena score can
        # distinguish models inside the same healthy pool. Five-point score bands
        # prevent tiny/noisy benchmark differences from constantly flipping routes.
        arena_band=-(int(arena_score)//5) if arena_ready else 0
        latency_key=round(arena_latency,2) if arena_ready else 999
        scored.append((
            health+feedback,
            arena_band,
            quality_rank,
            latency_key,
            model,
            provider,
            health,
            feedback,
            arena_score,
        ))
    scored.sort()
    _,_,_,_,model,provider,health,feedback,arena_score=scored[0]
    return model,provider,health+feedback,{
        "ready":arena_ready,
        "score":arena_score if arena_ready else None,
        "scores":arena_scores if arena_ready else {},
    }


def resolve_route(decision,providers,models):
    """Select one strong main brain; tools/support models stay underneath it."""
    openrouter=bool(providers.get("openrouter"))

    if decision.get("specialist")=="vision":
        if openrouter:
            selected=models["or_qwen"]
        else:
            selected=models["vision"]
        decision["main_brain_selected"]=selected
        decision["main_brain_policy"]="vision-capability-boundary"
        return selected,"vision"

    depth=str(decision.get("depth") or "smart")
    selected,provider,penalty,arena=_pick_main_brain(providers,models)
    decision["main_brain_selected"]=selected
    decision["main_brain_provider"]=provider
    decision["main_brain_penalty"]=penalty
    decision["main_brain_arena"]=arena
    decision["main_brain_policy"]="quality-first + health-aware + objective-arena-aware"

    if depth=="apex":
        return selected,"apex"
    if depth=="deep":
        return selected,"deep"
    return selected,"knowledge"


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
        "policy":"strongest-main-brain + health-aware failover + objective Brain Arena + selective capability plane",
        "main_brain_health_aware":True,
        "brain_arena_aware":True,
        "council_default":False,
        "competition_threshold":"difficulty>=6 only",
    }
