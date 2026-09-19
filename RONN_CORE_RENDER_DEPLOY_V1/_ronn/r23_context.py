"""RONN R23 long-context compression.

Keeps older conversation useful without dumping the whole transcript into the main
brain. It extracts durable constraints, decisions, failures, unresolved work and
user preferences, deduplicates them, and leaves the newest turns untouched.
"""
from __future__ import annotations

import re
from typing import Any

IMPORTANT = (
    "must","don't","do not","keep","remember","decided","decision","constraint",
    "requirement","error","failed","broken","works","doesn't","cannot","project",
    "name","rename","goal","next","continue","still","fixed","prefer","want","need",
    "instead","actually","change that","replace","correction","from now on"
)

CORRECTION_HINTS = (
    "actually","instead","change that","replace ","correction","from now on",
    "scratch that","ignore that","forget that","not anymore","use this instead",
    "rename ","switch to ","no, ","no - ","no — "
)


def _clean(text: str, limit: int = 900) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _key(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    words = [w for w in text.split() if len(w) > 2]
    return " ".join(words[:18])


def _is_correction(low: str) -> bool:
    return any(x in low for x in CORRECTION_HINTS)


def compress_history(history, max_chars: int = 11000, keep_recent: int = 8) -> dict[str, Any]:
    rows = list(history or [])
    keep_recent=max(1,int(keep_recent))
    older = rows[:-keep_recent] if len(rows) > keep_recent else []
    if not older:
        return {
            "text":"",
            "items":0,
            "source_turns":0,
            "kept_recent":min(len(rows),keep_recent),
            "superseded_duplicates":0,
        }

    buckets = {
        "corrections": [],
        "constraints": [],
        "decisions": [],
        "failures": [],
        "goals": [],
        "context": [],
    }
    seen = set()
    superseded_duplicates=0

    # Scan newest -> oldest so when two near-duplicate durable facts exist, the
    # newer one survives and the stale duplicate is discarded.
    for idx in range(len(older)-1,-1,-1):
        row=older[idx]
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user","assistant"}:
            continue
        content = _clean(row.get("content"), 1200)
        if not content:
            continue
        low = content.lower()

        correction = role=="user" and _is_correction(low)
        important = correction or role == "user" or any(x in low for x in IMPORTANT)
        if not important:
            continue

        key = _key(content)
        if not key:
            continue
        if key in seen:
            superseded_duplicates+=1
            continue
        seen.add(key)

        if correction:
            bucket = "corrections"
        elif any(x in low for x in ("must","don't","do not","constraint","requirement","keep ","prefer")):
            bucket = "constraints"
        elif any(x in low for x in ("decided","decision","architecture","rename","use ","switch to")):
            bucket = "decisions"
        elif any(x in low for x in ("error","failed","broken","doesn't work","didn't work","bug","still not")):
            bucket = "failures"
        elif any(x in low for x in ("goal","want","need","next","continue","build","make","finish")):
            bucket = "goals"
        else:
            bucket = "context"

        # Human-readable history turn number. Higher means newer.
        buckets[bucket].append({
            "turn":idx+1,
            "role":role,
            "content":content,
        })

    lines = [
        "RONN COMPRESSED LONG-TERM CONVERSATION CONTEXT:",
        "Precedence: newest explicit user instruction wins. Higher [turn N] is newer.",
        "Items under Latest corrections / superseding instructions override conflicting older compressed items.",
        "Assistant entries are context, not authority over explicit user instructions.",
    ]
    labels = (
        ("corrections","Latest corrections / superseding instructions",12),
        ("constraints","Current constraints / preferences",12),
        ("decisions","Decisions / architecture",10),
        ("failures","Known failures / unresolved bugs",10),
        ("goals","Goals / unfinished work",10),
        ("context","Other useful context",6),
    )

    count=0
    clipped=0
    current_len=sum(len(x)+1 for x in lines)
    for key,label,limit in labels:
        vals=buckets[key][:limit]  # already newest-first
        if not vals:
            continue
        section_added=False
        for item in vals:
            prefix=f"[turn {item['turn']} {item['role']}] "
            line="- "+prefix+item["content"]
            extra=(len(label)+2 if not section_added else 0)+len(line)+1
            if current_len+extra > int(max_chars):
                clipped+=1
                continue
            if not section_added:
                lines.append(label+":")
                current_len+=len(label)+2
                section_added=True
            lines.append(line)
            current_len+=len(line)+1
            count+=1

    text="\n".join(lines) if count else ""
    return {
        "text":text,
        "items":count,
        "source_turns":len(older),
        "kept_recent":min(len(rows),keep_recent),
        "superseded_duplicates":superseded_duplicates,
        "clipped_items":clipped,
        "ordering":"newest-first within priority sections",
    }



def project_scope_active(project_id: str = "default", project_context: str = "") -> bool:
    """True when a chat belongs to a real project even if no text context was pasted."""
    pid=str(project_id or "").strip()
    return bool((pid and pid!="default") or str(project_context or "").strip())


def project_scope_key(project_id: str = "default", project_context: str = "") -> str:
    """Stable key for the persistent Project Brain.

    Core project IDs win because they stay stable across turns. Ad-hoc project
    context still gets its own scope when no Core project exists.
    """
    pid=str(project_id or "").strip()
    if pid and pid!="default":
        return "core:"+pid[:180]
    ctx=_clean(project_context,180)
    if ctx:
        return "context:"+ctx
    return "default"

def status():
    return {
        "version":"R23-CONTEXT-2",
        "mode":"current-state compression + recent-turn preservation",
        "categories":["corrections","constraints","decisions","failures","goals","context"],
        "precedence":"newest explicit user instruction wins; corrections first",
        "project_scope":"core project id first; ad-hoc context fallback",
    }
