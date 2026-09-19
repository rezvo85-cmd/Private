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
    "name","rename","goal","next","continue","still","fixed","prefer","want","need"
)


def _clean(text: str, limit: int = 900) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _key(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    words = [w for w in text.split() if len(w) > 2]
    return " ".join(words[:18])


def compress_history(history, max_chars: int = 11000, keep_recent: int = 8) -> dict[str, Any]:
    rows = list(history or [])
    older = rows[:-max(1, int(keep_recent))] if len(rows) > keep_recent else []
    if not older:
        return {"text":"","items":0,"source_turns":0,"kept_recent":min(len(rows),keep_recent)}

    buckets = {
        "constraints": [],
        "decisions": [],
        "failures": [],
        "goals": [],
        "context": [],
    }
    seen = set()

    for row in older:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user","assistant"}:
            continue
        content = _clean(row.get("content"), 1200)
        if not content:
            continue
        low = content.lower()

        # User statements get priority because they define the goal.
        important = role == "user" or any(x in low for x in IMPORTANT)
        if not important:
            continue

        key = _key(content)
        if not key or key in seen:
            continue
        seen.add(key)

        if any(x in low for x in ("must","don't","do not","constraint","requirement","keep ","prefer")):
            bucket = "constraints"
        elif any(x in low for x in ("decided","decision","architecture","rename","use ","switch to")):
            bucket = "decisions"
        elif any(x in low for x in ("error","failed","broken","doesn't work","didn't work","bug","still not")):
            bucket = "failures"
        elif any(x in low for x in ("goal","want","need","next","continue","build","make","finish")):
            bucket = "goals"
        else:
            bucket = "context"

        buckets[bucket].append(f"{role}: {content}")

    lines = ["RONN COMPRESSED LONG-TERM CONVERSATION CONTEXT:"]
    labels = (
        ("constraints","Constraints"),
        ("decisions","Decisions"),
        ("failures","Known failures"),
        ("goals","Goals / unfinished work"),
        ("context","Other useful context"),
    )
    count = 0
    for key, label in labels:
        vals = buckets[key][-10:]
        if not vals:
            continue
        lines.append(label + ":")
        for val in vals:
            lines.append("- " + val)
            count += 1

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[-max_chars:]
        # Avoid starting in the middle of a line if clipped.
        first = text.find("\n")
        if first >= 0:
            text = "RONN COMPRESSED LONG-TERM CONVERSATION CONTEXT:\n" + text[first+1:]

    return {
        "text": text if count else "",
        "items": count,
        "source_turns": len(older),
        "kept_recent": min(len(rows),keep_recent),
    }


def status():
    return {
        "version":"R23-CONTEXT-1",
        "mode":"structured compression + recent-turn preservation",
        "categories":["constraints","decisions","failures","goals","context"],
    }
