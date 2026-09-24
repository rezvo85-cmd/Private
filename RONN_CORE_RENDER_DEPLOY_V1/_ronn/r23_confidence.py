"""R23 current-turn confidence governor.

This layer converts uncertainty in the *current* routing decision into more
reasoning/verification only when the task earns it. It never overrides an
explicit user-selected mode and it keeps easy turns on the fast path.
"""
from __future__ import annotations

from typing import Any

VERSION="R23-CONFIDENCE-GOVERNOR-1"
VERIFY_THRESHOLD=.72
DEEP_THRESHOLD=.64
COMPETITION_THRESHOLD=.50
APEX_THRESHOLD=.38


def _clamp(value: float) -> float:
    return max(0.0,min(1.0,float(value)))


def _score_margin(signal: dict, selected: str, field: str="score", scale: float=100.0):
    if not signal or not signal.get("ready"):
        return None
    scores=signal.get("scores") or {}
    row=scores.get(selected) or {}
    if field not in row:
        return None
    try:
        chosen=float(row.get(field) or 0)
    except Exception:
        return None
    others=[]
    for model,item in scores.items():
        if model==selected:
            continue
        try:
            others.append(float((item or {}).get(field) or 0))
        except Exception:
            pass
    if not others:
        return None
    return (chosen-max(others))/max(1.0,float(scale))


def confidence_signal(decision: dict, selected: str, provider_penalty: int, signals: dict) -> dict[str,Any]:
    decision=decision or {}
    signals=signals or {}
    difficulty=max(1,int(decision.get("difficulty") or 1))
    score=.62
    reasons=[]
    evidence=[]

    objective_specs=(
        ("quality_lab",.16),
        ("domain_arena",.14),
        ("arena",.10),
    )
    margins=[]
    for name,weight in objective_specs:
        sig=signals.get(name) or {}
        if sig.get("ready"):
            score+=weight
            evidence.append(name)
            margin=_score_margin(sig,selected,"score",100.0)
            if margin is not None:
                margins.append((name,margin))

    outcomes=signals.get("outcomes") or {}
    if outcomes.get("ready"):
        row=(outcomes.get("scores") or {}).get(selected) or {}
        ratings=int(row.get("ratings") or 0)
        if ratings>=3:
            score+=.08
            evidence.append("profile_outcomes")
            margin=_score_margin(outcomes,selected,"avg_rating",2.0)
            if margin is not None:
                margins.append(("profile_outcomes",margin))

    if not evidence and difficulty>=3:
        score-=.10
        reasons.append("no_fresh_shared_selection_evidence")

    # Close objective races deserve caution. Clear leads earn a small confidence
    # bonus, but never enough to erase health/difficulty pressure.
    if margins:
        strongest=max(m for _n,m in margins)
        weakest=min(m for _n,m in margins)
        if weakest<=.03:
            score-=.06
            reasons.append("close_or_trailing_model_race")
        elif strongest>=.15:
            score+=.05
            reasons.append("clear_model_lead")

    if difficulty>=4:
        score-=.08
        reasons.append("hard_task")
    if difficulty>=6:
        score-=.10
        reasons.append("very_hard_task")

    penalty=max(0,int(provider_penalty or 0))
    if penalty:
        score-=min(.16,.035*penalty)
        reasons.append("provider_or_feedback_penalty")

    score=_clamp(score)
    if score>=.78:
        level="high"
    elif score>=.62:
        level="medium"
    elif score>=.45:
        level="low"
    else:
        level="very_low"

    return {
        "version":VERSION,
        "score":round(score,3),
        "level":level,
        "difficulty":difficulty,
        "model":str(selected or ""),
        "evidence":evidence,
        "margins":{name:round(value,3) for name,value in margins},
        "reasons":reasons,
        "thresholds":{
            "verify":VERIFY_THRESHOLD,
            "deep":DEEP_THRESHOLD,
            "competition":COMPETITION_THRESHOLD,
            "apex":APEX_THRESHOLD,
        },
    }


def apply_confidence_governor(decision: dict, selected: str, provider_penalty: int, signals: dict) -> dict[str,Any]:
    decision=decision or {}
    signal=confidence_signal(decision,selected,provider_penalty,signals)
    mode=str(decision.get("explicit_mode") or "auto").strip().lower()
    difficulty=int(decision.get("difficulty") or 1)
    before=str(decision.get("depth") or "smart")
    result=dict(signal)
    result.update({
        "applied":False,
        "depth_before":before,
        "depth_after":before,
        "verification_added":False,
        "correction_pass_added":False,
        "competition_added":False,
        "reason":"confidence_sufficient",
    })

    if mode!="auto":
        result["reason"]="explicit_mode_preserved"
        decision["main_brain_confidence"]=result
        return result
    if difficulty<=2:
        result["reason"]="easy_turn_preserved"
        decision["main_brain_confidence"]=result
        return result

    score=float(signal.get("score") or 0)
    policy=dict(decision.get("prompt_policy") or {})
    verification_added=False
    correction_added=False
    competition_added=False
    after=before

    if score<VERIFY_THRESHOLD and not bool(decision.get("verify")):
        decision["verify"]=True
        verification_added=True
        policy["include_verification_directive"]=True
        policy["include_failure_lessons"]=True
        policy["include_evidence_plan"]=True

    if score<DEEP_THRESHOLD and difficulty>=4 and before in {"fast","smart"}:
        after="deep"

    live=bool(decision.get("needs_live"))
    vision=str(decision.get("specialist") or "")=="vision"
    if score<COMPETITION_THRESHOLD and difficulty>=5 and not live and not vision:
        if not bool(decision.get("use_council")):
            decision["use_council"]=True
            competition_added=True
        # Council already supplies independent challenge + judge + synthesis.
        decision["second_pass"]=False
    elif score<.58 and difficulty>=4 and not live and not vision:
        if not bool(decision.get("second_pass")):
            decision["second_pass"]=True
            correction_added=True

    if score<APEX_THRESHOLD and difficulty>=6:
        after="apex"

    if after!=before:
        decision["depth"]=after
    decision["prompt_policy"]=policy

    applied=bool(
        verification_added or correction_added or competition_added or after!=before
    )
    result.update({
        "applied":applied,
        "depth_after":after,
        "verification_added":verification_added,
        "correction_pass_added":correction_added,
        "competition_added":competition_added,
        "verify":bool(decision.get("verify")),
        "second_pass":bool(decision.get("second_pass")),
        "use_council":bool(decision.get("use_council")),
        "reason":"current_turn_uncertainty_escalation" if applied else "confidence_sufficient",
    })
    decision["main_brain_confidence"]=result
    return result


def status() -> dict[str,Any]:
    return {
        "version":VERSION,
        "enabled":True,
        "auto_mode_only":True,
        "easy_turns_preserved":True,
        "verify_threshold":VERIFY_THRESHOLD,
        "deep_threshold":DEEP_THRESHOLD,
        "competition_threshold":COMPETITION_THRESHOLD,
        "apex_threshold":APEX_THRESHOLD,
        "signals":["quality_lab","domain_arena","arena","profile_outcomes","provider_health","task_difficulty"],
    }
