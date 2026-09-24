"""Optional Docling backend for RONN's single document engine.

This module never owns document routing or user-facing behavior. document_engine.py
remains the interface of record and calls this backend only for supported formats.
Imports and converter construction are lazy so normal chat startup stays light.
"""
from __future__ import annotations

import io
import os
import threading
from importlib.util import find_spec
from pathlib import Path
from typing import Any

VERSION = "R23-DOCLING-ADAPTER-1"
_ENABLED = os.getenv("RONN_DOCLING_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
_SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".markdown"}
_LOCK = threading.Lock()
_CONVERTER = None


def available() -> bool:
    return bool(_ENABLED and find_spec("docling") is not None)


def supported(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in _SUPPORTED


def _converter():
    global _CONVERTER
    if _CONVERTER is not None:
        return _CONVERTER
    with _LOCK:
        if _CONVERTER is None:
            from docling.document_converter import DocumentConverter
            _CONVERTER = DocumentConverter()
    return _CONVERTER


def extract(filename: str, raw: bytes, max_chars: int = 80000, max_pages: int = 120) -> dict[str, Any]:
    """Return a normalized extraction result or a bounded failure description."""
    if not _ENABLED:
        return {"ok": False, "reason": "disabled", "backend": "docling"}
    if not supported(filename):
        return {"ok": False, "reason": "unsupported_extension", "backend": "docling"}
    if find_spec("docling") is None:
        return {"ok": False, "reason": "not_installed", "backend": "docling"}

    try:
        from docling.datamodel.base_models import DocumentStream

        stream = DocumentStream(name=filename or "document", stream=io.BytesIO(raw))
        result = _converter().convert(
            stream,
            raises_on_error=True,
            max_num_pages=max(1, min(int(max_pages), 200)),
            max_file_size=max(len(raw) + 1, 1024),
        )
        document = result.document
        markdown = str(document.export_to_markdown() or "").strip()
        if not markdown:
            return {"ok": False, "reason": "empty_output", "backend": "docling"}

        structural = {}
        try:
            exported = document.export_to_dict()
            if isinstance(exported, dict):
                for key in ("texts", "tables", "pictures", "pages", "groups", "key_value_items"):
                    value = exported.get(key)
                    if isinstance(value, (list, tuple, dict)):
                        structural[key] = len(value)
        except Exception:
            structural = {}

        return {
            "ok": True,
            "text": markdown[:max_chars],
            "backend": "docling",
            "meta": {
                "docling_version": VERSION,
                "structured_counts": structural,
                "truncated": len(markdown) > max_chars,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "reason": exc.__class__.__name__,
            "backend": "docling",
        }


def status() -> dict[str, Any]:
    return {
        "version": VERSION,
        "enabled": _ENABLED,
        "installed": find_spec("docling") is not None,
        "available": available(),
        "lazy": True,
        "supported_extensions": sorted(_SUPPORTED),
        "owns_routing": False,
        "owns_final_answer": False,
    }
