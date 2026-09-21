"""RONN R23 unified brain.

R23 keeps the R22 rule: one main brain owns the answer. The eleven major
capabilities sit underneath it as tools/evidence, not as competing prompt layers.
"""
from __future__ import annotations

from r22_lean_core import plan as r22_plan
from r23_capabilities import capability_plan, status as capability_status
from provider_engine import model_penalty
from experience_engine import model_feedback_penalty, profile_feedback_signal
from r23_brain_arena import (
    routing_signal as arena_routing_signal,
    domain_signal as arena_domain_signal,
    challenger_signal as arena_challenger_signal,
)
from r23_quality_lab import quality_signal as r23_quality_signal

R23_VERSION="R23-UNIFIED-BRAIN-1"

_REASONING_FLOORS={
    "fast":0,
    "smart":900,
    "deep":1800,
    "apex":3000,
}


def reasoning_effort_for_depth(depth: str) -> str:
    depth=str(depth or "smart").lower()
    if depth=="fast":
        return "low"
    if depth in {"deep","apex"}:
        return "high"
    return "medium"


def reasoning_effort_for_route(route: str) -> str:
    """Provider-facing effort level derived from the actual request route."""
    route=str(route or "").lower()
    if route=="fast":
        return "low"
    if (
        "apex" in route
        or "deep" in route
        or "review" in route
        or route in {"ultra","tools","r20-reasoning","r20-code"}
    ):
        return "high"
    return "medium"


def reasoning_completion_budget(depth: str, visible_max_tokens: int) -> int:
    """Keep visible brevity separate from the total reasoning completion budget."""
    depth=str(depth or "smart").lower()
    visible=max(1,int(visible_max_tokens or 1))
    floor=int(_REASONING_FLOORS.get(depth,900))
    return max(visible,floor)


def reasoning_contract(decision: dict) -> str:
    depth=str((decision or {}).get("depth") or "smart").lower()
    effort=reasoning_effort_for_depth(depth)
    if depth=="fast":
        rules=(
            "Solve directly. Use only the reasoning needed to avoid an obvious mistake."
        )
    elif depth=="deep":
        rules=(
            "Before answering, privately decompose the task into requirements and constraints; "
            "check important assumptions, edge cases, and one plausible counterexample/failure mode; "
            "then verify the final conclusion against the user's explicit requirements."
        )
    elif depth=="apex":
        rules=(
            "Before answering, privately form at least two plausible solution paths or hypotheses when applicable; "
            "compare their failure modes and tradeoffs, adversarially test the strongest option, reconcile contradictions, "
            "and verify the final result against every explicit requirement and available evidence."
        )
    else:
        rules=(
            "Privately identify the key requirement, solve it carefully, and do a short sanity check before answering."
        )
    return (
        "RONN REASONING EFFORT:\n"
        f"- Depth: {depth}; provider effort target: {effort}.\n"
        f"- {rules}\n"
        "- Keep private reasoning private. Return only the polished answer, not chain-of-thought or scratch work."
    )


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
        "explicit_mode":str(explicit_mode or "auto").strip().lower(),
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


def competition_pair(primary_model, profile, providers, models):
    """Return a two-model hard-task pair with the learned main brain first.

    Candidate A always preserves the R23-selected main brain. Candidate B favors
    a materially different specialist for the task when available, then a strong
    alternate main brain. This keeps competition diverse without discarding the
    routing evidence already used to choose the primary.
    """
    primary=str(primary_model or "")
    profile=str(profile or "chat").lower()
    pool=[]

    def add(model,role):
        model=str(model or "")
        if model and model not in [x["model"] for x in pool]:
            pool.append({"model":model,"role":role})

    if primary:
        add(primary,"r23_primary")

    if providers.get("openrouter"):
        # Certified challengers shadow the incumbent on real hard tasks before
        # they are allowed to become a primary brain. Task-relevant ordering
        # keeps the comparison useful rather than random.
        challenger_order=(
            ("or_deepseek","or_qwen") if profile=="coding"
            else (("or_qwen","or_deepseek") if profile in {"writing","analysis","knowledge","research","mathscience"} else ())
        )
        for key in challenger_order:
            challenger=str(models.get(key) or "")
            if not challenger or challenger==primary:
                continue
            signal=arena_challenger_signal(challenger,profile)
            if signal.get("certified"):
                add(challenger,"certified_shadow_challenger")

        if profile=="coding":
            add(models.get("or_deepseek"),"coding_specialist")
        elif profile in {"creative","writing"}:
            add(models.get("or_qwen"),"general_specialist")

    for model,provider,_rank in _main_brain_candidates(providers,models):
        add(model,"alternate_main")

    if providers.get("openrouter"):
        add(models.get("or_qwen"),"diverse_general")
        add(models.get("or_deepseek"),"diverse_coding")
    if providers.get("nvidia"):
        add(models.get("nvidia"),"alternate_main")
    if providers.get("groq"):
        add(models.get("smart"),"alternate_main")

    if not pool:
        add(models.get("smart"),"fallback")

    pair=pool[:2]
    return {
        "models":[x["model"] for x in pair],
        "roles":[x["role"] for x in pair],
        "primary_preserved":bool(pair and primary and pair[0]["model"]==primary),
        "diverse":len(pair)>=2 and pair[0]["model"]!=pair[1]["model"],
        "profile":profile,
    }


def _pick_main_brain(providers,models,profile="chat"):
    """Pick the strongest healthy configured brain.

    Default quality order is Nemotron Ultra -> NVIDIA Nemotron -> GPT-OSS 120B.
    Repeated provider failures or multiple negative user ratings can temporarily
    demote a model so RONN does not keep paying a failed first-attempt penalty.
    """
    candidates=_main_brain_candidates(providers,models)
    challenger_signals={}
    if providers.get("openrouter"):
        for key,rank in (("or_deepseek",3),("or_qwen",4)):
            challenger=str(models.get(key) or "")
            if not challenger or any(challenger==x[0] for x in candidates):
                continue
            signal=arena_challenger_signal(challenger,profile)
            challenger_signals[challenger]=signal
            if signal.get("eligible"):
                candidates.append((challenger,"openrouter",rank))
    if not candidates:
        return models["smart"],"unknown",0,{
            "arena":{"ready":False,"scores":{}},
            "domain_arena":{"domain":"","ready":False,"scores":{}},
            "outcomes":{"profile":str(profile or "chat"),"ready":False,"scores":{}},
            "quality_lab":{"ready":False,"tier":"","scores":{}},
            "challengers":challenger_signals,
        }

    candidate_models=[m for m,_,_ in candidates]
    arena=arena_routing_signal(candidate_models)
    arena_ready=bool(arena.get("ready"))
    arena_scores=arena.get("scores") or {}
    domain_arena=arena_domain_signal(candidate_models,profile)
    domain_ready=bool(domain_arena.get("ready"))
    domain_scores=domain_arena.get("scores") or {}
    outcomes=profile_feedback_signal(candidate_models,profile,3)
    outcome_ready=bool(outcomes.get("ready"))
    outcome_scores=outcomes.get("scores") or {}
    quality_lab=r23_quality_signal(candidate_models,"auto")
    quality_ready=bool(quality_lab.get("ready"))
    quality_scores=quality_lab.get("scores") or {}

    scored=[]
    for model,provider,quality_rank in candidates:
        health=int(model_penalty(model) or 0)
        feedback=int(model_feedback_penalty(model) or 0)
        row=arena_scores.get(model) or {}
        arena_score=float(row.get("score") or 0)
        arena_latency=float(row.get("latency") or 999)
        domain_row=domain_scores.get(model) or {}
        domain_score=float(domain_row.get("score") or 0)
        domain_latency=float(domain_row.get("latency") or 999)
        outcome_row=outcome_scores.get(model) or {}
        outcome_avg=float(outcome_row.get("avg_rating") or 0)
        outcome_penalty=int(outcome_row.get("penalty") or 0)
        quality_row=quality_scores.get(model) or {}
        quality_score=float(quality_row.get("score") or 0)

        # Reliability is the hard guardrail. Repeated negative feedback for this
        # specific task profile can independently demote a model. Positive outcome
        # ranking activates only when every candidate has enough fair coverage.
        profile_band=-int(round(outcome_avg*4)) if outcome_ready else 0
        domain_band=-(int(domain_score)//5) if domain_ready else 0
        quality_band=-(int(quality_score)//5) if quality_ready else 0
        arena_band=-(int(arena_score)//5) if arena_ready else 0
        latency_key=round(
            float(quality_row.get("latency") or 999)
            if quality_ready else (domain_latency if domain_ready else arena_latency),
            2,
        ) if (quality_ready or domain_ready or arena_ready) else 999
        scored.append((
            health+feedback+outcome_penalty,
            profile_band,
            domain_band,
            quality_band,
            arena_band,
            quality_rank,
            latency_key,
            model,
            provider,
            health,
            feedback,
            arena_score,
            domain_score,
            quality_score,
            outcome_avg,
        ))
    scored.sort()
    _,_,_,_,_,_,_,model,provider,health,feedback,arena_score,domain_score,quality_score,outcome_avg=scored[0]
    return model,provider,health+feedback,{
        "arena":{"ready":arena_ready,"score":arena_score if arena_ready else None,"scores":arena_scores if arena_ready else {}},
        "domain_arena":{
            "domain":domain_arena.get("domain") or "",
            "ready":domain_ready,
            "score":domain_score if domain_ready else None,
            "scores":domain_scores if domain_ready else {},
        },
        "outcomes":{"profile":profile,"ready":outcome_ready,"score":outcome_avg if model in outcome_scores else None,"scores":outcome_scores},
        "quality_lab":{
            "ready":quality_ready,
            "tier":quality_lab.get("tier") or "",
            "case_count":quality_lab.get("case_count") or 0,
            "score":quality_score if quality_ready else None,
            "scores":quality_scores if quality_ready else {},
        },
        "challengers":challenger_signals,
    }


def _apply_adaptive_effort(decision,selected,outcome_signal):
    """Raise effort only when repeated profile outcomes justify it.

    User-selected modes always win. Easy tasks are never escalated by feedback.
    """
    mode=str(decision.get("explicit_mode") or "auto").strip().lower()
    difficulty=int(decision.get("difficulty") or 1)
    before=str(decision.get("depth") or "smart")
    scores=(outcome_signal or {}).get("scores") or {}
    row=scores.get(selected) or {}
    ratings=int(row.get("ratings") or 0)
    avg=float(row.get("avg_rating") or 0)

    result={
        "applied":False,
        "profile":str(decision.get("profile") or "chat"),
        "model":selected,
        "ratings":ratings,
        "avg_rating":avg if ratings else None,
        "depth_before":before,
        "depth_after":before,
        "verification_added":False,
        "reason":"insufficient_or_inapplicable_evidence",
    }
    if mode!="auto":
        result["reason"]="explicit_mode_preserved"
        decision["adaptive_effort"]=result
        return result
    if difficulty<3 or ratings<3:
        decision["adaptive_effort"]=result
        return result
    if avg>=0:
        result["reason"]="outcomes_not_negative"
        decision["adaptive_effort"]=result
        return result

    after=before
    if avg<=-.5:
        if before in {"fast","smart"}:
            after="deep"
        elif before=="deep" and difficulty>=6:
            after="apex"
    elif avg<0 and difficulty>=4 and before=="smart":
        after="deep"

    verify_added=False
    if avg<=-.5 and difficulty>=4 and not bool(decision.get("verify")):
        decision["verify"]=True
        verify_added=True
        policy=dict(decision.get("prompt_policy") or {})
        policy["include_verification_directive"]=True
        policy["include_failure_lessons"]=True
        policy["include_evidence_plan"]=True
        decision["prompt_policy"]=policy

    # Strong repeated negative outcomes on a non-trivial auto-mode task earn a
    # real draft/audit/critic/final correction pass. This is deliberately more
    # selective than merely raising depth and never applies to easy turns.
    correction_pass_added=False
    if avg<=-.5 and difficulty>=4 and not bool(decision.get("needs_live")) and decision.get("specialist")!="vision":
        if not bool(decision.get("second_pass")):
            decision["second_pass"]=True
            correction_pass_added=True

    if after!=before:
        decision["depth"]=after

    applied=bool(after!=before or verify_added or correction_pass_added)
    result.update({
        "applied":applied,
        "depth_after":after,
        "verification_added":verify_added,
        "correction_pass_added":correction_pass_added,
        "second_pass":bool(decision.get("second_pass")),
        "reason":"repeated_negative_profile_outcomes" if applied else "negative_but_below_escalation_threshold",
    })
    decision["adaptive_effort"]=result
    return result


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

    profile=str(decision.get("profile") or "chat")
    selected,provider,penalty,signals=_pick_main_brain(providers,models,profile)
    decision["main_brain_selected"]=selected
    decision["main_brain_provider"]=provider
    decision["main_brain_penalty"]=penalty
    decision["main_brain_arena"]=signals.get("arena") or {}
    decision["main_brain_domain_arena"]=signals.get("domain_arena") or {}
    decision["main_brain_outcomes"]=signals.get("outcomes") or {}
    decision["main_brain_quality_lab"]=signals.get("quality_lab") or {}
    decision["main_brain_challengers"]=signals.get("challengers") or {}
    _apply_adaptive_effort(decision,selected,decision["main_brain_outcomes"])
    decision["main_brain_policy"]="quality-first + health-aware + proven-challengers + domain-arena-aware + progressive-quality-lab + objective-arena-aware + profile-outcome-aware + adaptive-effort"

    depth=str(decision.get("depth") or "smart")
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
        + reasoning_contract(decision) + "\n"
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
        "domain_brain_arena":True,
        "progressive_quality_lab":True,
        "quality_lab_routing_rule":"only when every compared candidate has the same complete fresh tier",
        "proven_main_brain_challengers":True,
        "profile_outcome_learning":True,
        "adaptive_outcome_effort":True,
        "provider_reasoning_effort":True,
        "reasoning_budget_decoupled_from_visible_brevity":True,
        "reasoning_effort_levels":{"fast":"low","smart":"medium","deep":"high","apex":"high"},
        "adaptive_effort_guardrails":"auto mode only; difficulty>=3; ratings>=3",
        "learned_self_correction":True,
        "self_correction_threshold":"strong negative profile outcomes; difficulty>=4; non-live non-vision",
        "apex_primary_ownership":True,
        "apex_competition_policy":"R23 primary first + diverse specialist/alternate; primary owns final synthesis",
        "council_default":False,
        "competition_threshold":"difficulty>=6 only",
    }
