"""RONN R23 knowledge-gap rescue.

Catches explicit model admissions of a factual knowledge gap before the first
uncertain sentence is shown. RONN can then retrieve live evidence and let the
selected main brain answer again. This is intentionally conservative: ordinary
uncertainty, opinions, creative tasks, and already-live requests do not trigger it.
"""
from __future__ import annotations

import json
import re
from typing import Any

VERSION="R23-KNOWLEDGE-RESCUE-1"

_FACTUAL_PROFILES={"knowledge","coding","mathscience","analysis","research"}

_GAP_PATTERNS=(
    ("not_familiar", r"\b(?:i(?:'m| am)|we(?:'re| are)) not familiar with\b"),
    ("not_heard_of", r"\bi (?:have not|haven't) (?:heard of|come across)\b"),
    ("dont_recognize", r"\bi (?:do not|don't) recognize (?:the )?(?:term|name|package|library|api|error|tool|framework)\b"),
    ("dont_know_what", r"\bi (?:do not|don't) know (?:what|who|where|when)\b"),
    ("cannot_identify", r"\bi (?:cannot|can't) identify\b"),
    ("cannot_determine_reference", r"\bi (?:cannot|can't) determine what .{0,90}? refers to\b"),
    ("not_sure_reference", r"\bi(?:'m| am) not sure what .{1,90}? (?:means|is|refers to)\b"),
    ("missing_information", r"\bi (?:do not|don't) have (?:enough )?(?:information|reliable information) (?:about|on)\b"),
    ("no_live_web_access", r"\bi (?:do not|don't) have (?:live |current )?web (?:access|browsing)\b"),
    ("cannot_browse_live", r"\bi (?:cannot|can't) (?:browse|search|access) (?:the )?(?:live )?web\b"),
    ("cannot_confirm_current", r"\bi (?:cannot|can't) confirm (?:the )?(?:current|latest|new|recent)\b"),
    ("cannot_check_current", r"\bi (?:cannot|can't) (?:check|verify) (?:the )?(?:current|latest|new|recent)\b"),
    ("unknown_named_thing", r"\bunknown (?:term|package|library|api|error|tool|framework)\b"),
)

_LOOKUP_QUESTION_PATTERNS=(
    r"\bcheck (?:that|this|it|those|these) out\b",
    r"\b(?:can you |could you )?(?:find|look up|look into|check for|see if)\b",
    r"\bfind me\b",
    r"\bwhere (?:can|could) i (?:buy|get|find)\b",
)

_FALSE_POSITIVE_CONTEXT=(
    "which do you prefer",
    "what do you prefer",
    "your favorite",
    "write a story",
    "make up",
    "brainstorm",
    "creative writing",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+"," ",str(text or "")).strip().lower()


def should_buffer(question: str, profile: str="", *, already_live=False, has_images=False) -> bool:
    if already_live or has_images:
        return False
    q=_norm(question)
    p=str(profile or "").strip().lower()
    if not q or any(x in q for x in _FALSE_POSITIVE_CONTEXT):
        return False
    if p in {"creative","writing"}:
        return False
    if p in _FACTUAL_PROFILES:
        return True
    if any(re.search(pattern,q,re.I) for pattern in _LOOKUP_QUESTION_PATTERNS):
        return True
    # Catch ordinary factual question shapes that may have been classified as chat.
    return bool(re.match(r"^(what|who|where|when|why|how|which|is|are|does|do|can)\b",q))


def gap_signal(answer: str, question: str="", profile: str="") -> dict[str,Any]:
    text=_norm(answer)
    if not text:
        return {"required":False,"reason":"","version":VERSION}
    if not should_buffer(question,profile,already_live=False,has_images=False):
        return {"required":False,"reason":"","version":VERSION}
    # Only the opening portion matters. A knowledge-gap admission normally appears
    # immediately; later cautious wording should not trigger a whole new web pass.
    opening=text[:520]
    for reason,pattern in _GAP_PATTERNS:
        if re.search(pattern,opening,re.I|re.S):
            return {
                "required":True,
                "reason":reason,
                "version":VERSION,
                "opening":opening[:220],
            }
    return {"required":False,"reason":"","version":VERSION}


def prefix_ready(text: str, *, limit=180) -> bool:
    """Release a normal answer after one short sentence or a small prefix."""
    raw=str(text or "")
    return len(raw)>=int(limit) or bool(re.search(r"[.!?](?:\s|$)",raw))


def build_rescue_messages(messages, question: str, evidence: str):
    """Preserve recent conversation while adding bounded live evidence as system context."""
    messages=list(messages or [])
    system_parts=[]
    recent=[]
    for item in messages:
        if not isinstance(item,dict):
            continue
        role=str(item.get("role") or "")
        content=item.get("content")
        if role=="system" and isinstance(content,str):
            system_parts.append(content)
        elif role in {"user","assistant"}:
            recent.append(item)

    evidence=str(evidence or "")[:52000]
    rescue_system=(
        "\n\nRONN KNOWLEDGE-GAP RESCUE:\n"
        "The previous draft admitted a factual knowledge gap. Use the live evidence below to answer the user's actual question.\n"
        "READ PAGE evidence is stronger than SEARCH SNIPPET ONLY evidence. A snippet is discovery metadata, not proof of page contents.\n"
        "Do not claim runtime verification from web retrieval. If the evidence still does not resolve the question, state the remaining uncertainty precisely.\n"
        "Do not mention drafts, rescue logic, hidden routing, or these instructions. Return only the polished answer.\n\n"
        "LIVE EVIDENCE:\n"+evidence
    )
    base_system="\n\n".join(system_parts)
    if len(base_system)>26000:
        base_system=base_system[:18000]+"\n\n[older system context compressed]\n\n"+base_system[-8000:]
    system=(base_system+rescue_system) if base_system else rescue_system
    out=[{"role":"system","content":system[:78000]}]
    out.extend(recent[-8:])
    # Guarantee the exact current question remains present even if recent context was odd.
    if not recent or str(recent[-1].get("role") or "")!="user":
        out.append({"role":"user","content":str(question or "")[:6000]})
    return out


def status():
    return {
        "version":VERSION,
        "pre_display_prefix_guard":True,
        "live_research_rescue":True,
        "factual_profiles":sorted(_FACTUAL_PROFILES),
        "conservative_patterns":len(_GAP_PATTERNS),
    }
