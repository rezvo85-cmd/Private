"""Current provider-model compatibility and live-route truthfulness helpers.

This module is deliberately below R23. It does not choose reasoning strategy or
become another router; it only prevents known-retired provider IDs from breaking
configured routes and keeps live-evidence labels honest.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any

VERSION = "PROVIDER-MODELS-1"

# Groq free/developer model IDs that are already decommissioned. These aliases
# only auto-migrate when CLOUD_API_BASE is the official Groq host, so custom
# OpenAI-compatible providers keep their explicitly configured identifiers.
_RETIRED_GROQ = {
    "qwen/qwen3.6-27b": {
        "replacement": "qwen/qwen3.8-27b",
        "shutdown": "2026-09-14",
    },
    "groq/compound-mini": {
        "replacement": "openai/gpt-oss-20b",
        "shutdown": "2026-09-21",
    },
    "groq/compound": {
        "replacement": "openai/gpt-oss-120b",
        "shutdown": "2026-09-21",
    },
    "meta-llama/llama-4-maverick-17b-128e-instruct": {
        "replacement": "openai/gpt-oss-120b",
        "shutdown": "2026-03-09",
    },
}

DEFAULTS = {
    "fast": "openai/gpt-oss-20b",
    "smart": "openai/gpt-oss-120b",
    "creator": "qwen/qwen3.8-27b",
    "vision": "qwen/qwen3.8-27b",
    # RONN's own SearXNG/Crawl4AI evidence plane handles freshness. These are
    # synthesis models, not hidden substitute search systems.
    "live": "openai/gpt-oss-20b",
    "research": "openai/gpt-oss-120b",
}


def official_groq_base(base_url: str) -> bool:
    try:
        return (urlparse(str(base_url or "")).hostname or "").strip().lower() == "api.groq.com"
    except Exception:
        return False


def normalize_groq_model(model: str, base_url: str) -> str:
    value=str(model or "").strip()
    if not value or not official_groq_base(base_url):
        return value
    if str(os.getenv("RONN_ALLOW_RETIRED_GROQ_MODELS") or "").strip().lower() in {"1","true","yes","on"}:
        return value
    row=_RETIRED_GROQ.get(value)
    return str((row or {}).get("replacement") or value)


def model_migration(model: str, base_url: str) -> dict[str, Any]:
    value=str(model or "").strip()
    normalized=normalize_groq_model(value,base_url)
    row=_RETIRED_GROQ.get(value) or {}
    return {
        "input":value,
        "effective":normalized,
        "migrated":bool(value and normalized != value),
        "shutdown":row.get("shutdown") or "",
        "official_groq_base":official_groq_base(base_url),
    }


def configured_model(env_name: str, default_key: str, base_url: str) -> str:
    raw=(os.getenv(env_name) or DEFAULTS[default_key]).strip()
    return normalize_groq_model(raw,base_url)


def live_synthesis_target(
    *,
    has_evidence: bool,
    r23: bool,
    current_model: str,
    groq: bool,
    openrouter: bool,
    nvidia: bool,
    smart_model: str,
    openrouter_model: str,
    nvidia_model: str,
) -> tuple[str,str]:
    """Choose only the synthesis model after RONN's real retrieval attempt.

    No evidence means no route is allowed to claim live research. We deliberately
    do not silently substitute provider model memory for missing web evidence.
    """
    if has_evidence:
        if r23:
            return current_model,"web-synthesis"
        if groq:
            return smart_model,"web-synthesis"
        if openrouter:
            return openrouter_model,"web-synthesis"
        if nvidia:
            return nvidia_model,"web-synthesis"
        return current_model,"web-synthesis"

    # Keep a capable answer model, but make the missing-live-evidence boundary
    # explicit to the prompt, UI metadata, and final audit.
    if groq:
        return smart_model,"research-limited"
    if openrouter:
        return openrouter_model,"research-limited"
    if nvidia:
        return nvidia_model,"research-limited"
    return current_model,"research-limited"


def status(base_url: str, models: dict[str,str]) -> dict[str,Any]:
    return {
        "version":VERSION,
        "official_groq_base":official_groq_base(base_url),
        "retired_ids":sorted(_RETIRED_GROQ),
        "models":{
            key:model_migration(value,base_url)
            for key,value in (models or {}).items()
        },
        "live_truthfulness":"no live label without retrieved evidence",
    }
