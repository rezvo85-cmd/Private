"""R23 explicit user-requirement contract.

Extracts high-signal constraints from the current user turn so the selected main
brain can privately verify exact requirements before finalizing. This does not
create new authority: user constraints remain subordinate to system/safety rules
and to verified tool/evidence boundaries.
"""
from __future__ import annotations

import re
from typing import Any

VERSION="R23-REQUIREMENT-CONTRACT-1"
MAX_ITEMS=8
MAX_ITEM_CHARS=260

_HARD_PATTERNS=(
    ("prohibition", re.compile(r"\b(?:do not|don't|dont|never|must not|cannot|can't|without|avoid)\b",re.I)),
    ("exactness", re.compile(r"\b(?:exactly|only|at least|at most|no more than|no less than|between\s+\d+|\d+\s*(?:sentences?|words?|items?|steps?|files?|models?))\b",re.I)),
    ("preservation", re.compile(r"\b(?:keep|preserve|retain|don't change|do not change|leave .* unchanged)\b",re.I)),
)
_SOFT_PATTERNS=(
    ("required", re.compile(r"\b(?:must|need to|needs to|required|make sure|ensure)\b",re.I)),
    ("format", re.compile(r"\b(?:reply|respond|return|format|output|short|brief|concise|paragraph|bullet|json|table)\b",re.I)),
    ("inclusion", re.compile(r"\b(?:include|add|use|with|contain)\b",re.I)),
)


def _clean(text: str) -> str:
    text=re.sub(r"\s+"," ",str(text or "")).strip(" \t\r\n-•")
    return text[:MAX_ITEM_CHARS]


def _segments(message: str):
    raw=str(message or "").strip()
    if not raw:
        return []
    # New lines and sentence boundaries are the safest unit: splitting every
    # conjunction tends to invent constraints that the user did not state.
    parts=re.split(r"(?:\n+|(?<=[.!?;])\s+)",raw)
    return [_clean(x) for x in parts if _clean(x)]


def extract_requirements(message: str, max_items: int=MAX_ITEMS) -> dict[str,Any]:
    items=[]
    seen=set()
    hard_count=0
    type_counts={}
    for segment in _segments(message):
        kinds=[]
        hard=False
        hard_hits=0
        for kind,pattern in _HARD_PATTERNS:
            matches=pattern.findall(segment)
            if matches:
                kinds.append(kind)
                hard=True
                hard_hits+=len(matches)
        for kind,pattern in _SOFT_PATTERNS:
            if pattern.search(segment):
                kinds.append(kind)
        if not kinds:
            continue
        key=re.sub(r"\W+"," ",segment.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        kinds=list(dict.fromkeys(kinds))
        if hard:
            hard_count+=1
        for kind in kinds:
            type_counts[kind]=type_counts.get(kind,0)+1
        items.append({
            "text":segment,
            "types":kinds,
            "hard":hard,
        })
        if len(items)>=max(1,int(max_items or MAX_ITEMS)):
            break

    count=len(items)
    if count>=5 or hard_count>=3:
        density="high"
    elif count>=2 or hard_count>=1:
        density="medium"
    elif count:
        density="low"
    else:
        density="none"

    return {
        "version":VERSION,
        "items":items,
        "count":count,
        "hard_count":hard_count,
        "density":density,
        "type_counts":type_counts,
        "truncated":count>=max(1,int(max_items or MAX_ITEMS)),
    }


def apply_requirement_contract(decision: dict, message: str) -> dict[str,Any]:
    decision=decision or {}
    contract=extract_requirements(message)
    decision["requirement_contract"]=contract
    if not contract.get("count"):
        return contract

    policy=dict(decision.get("prompt_policy") or {})
    policy["include_requirement_contract"]=True

    # Dense exact constraints are a concrete correctness risk on non-trivial
    # tasks. Add verification, but do not automatically force an extra model call;
    # the confidence governor decides whether a correction/council pass is earned.
    difficulty=int(decision.get("difficulty") or 1)
    if difficulty>=3 and (
        int(contract.get("count") or 0)>=4
        or int(contract.get("hard_count") or 0)>=2
    ):
        decision["verify"]=True
        policy["include_verification_directive"]=True

    decision["prompt_policy"]=policy
    return contract


def directive_text(contract: dict) -> str:
    contract=contract or {}
    items=list(contract.get("items") or [])
    if not items:
        return ""
    rows=[]
    for i,item in enumerate(items[:MAX_ITEMS],1):
        rows.append(f"{i}. {str(item.get('text') or '')[:MAX_ITEM_CHARS]}")
    return (
        "RONN REQUIREMENT CONTRACT (current user turn):\n"
        + "\n".join(rows)
        + "\n- Privately check every applicable item before finalizing. "
          "Do not claim success for requirements that evidence/tools did not verify. "
          "These are user-level constraints and never override higher-priority safety/system rules."
    )


def status() -> dict[str,Any]:
    return {
        "version":VERSION,
        "enabled":True,
        "max_items":MAX_ITEMS,
        "current_turn_only":True,
        "dense_contract_adds_verification":True,
        "extra_model_call":False,
        "authority":"user-level constraints remain subordinate to system/safety/evidence boundaries",
    }
