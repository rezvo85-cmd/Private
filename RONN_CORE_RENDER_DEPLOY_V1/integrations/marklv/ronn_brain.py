"""R23 reasoning bridge for the local RONN/Mark-LV desktop shell."""
from __future__ import annotations

from core.ronn_core import RonnCoreError, client


def ronn_brain(parameters: dict, player=None) -> str:
    message = str(parameters.get("message") or "").strip()
    project_context = str(parameters.get("project_context") or "").strip()
    mode = str(parameters.get("mode") or "auto").strip().lower()
    if mode not in {"auto", "max", "apex", "fast"}:
        mode = "auto"
    try:
        result = client().ask(
            message,
            mode=mode,
            project_context=project_context,
            agent_mode=True,
        )
        answer = str(result.get("answer") or "").strip()
        if player:
            try:
                route = result.get("route") or "R23"
                model = result.get("model") or ""
                suffix = f" / {model}" if model else ""
                player.write_log(f"RONN BRAIN: {route}{suffix}")
            except Exception:
                pass
        return answer
    except RonnCoreError as exc:
        return f"RONN brain connection error: {exc}"
    except Exception as exc:
        return f"RONN brain failed: {exc}"


TOOL = {
    "name": "ronn_brain",
    "description": (
        "Delegates nontrivial reasoning to RONN R23 on the existing RONN Core backend. "
        "Use for coding/debugging analysis, Roblox project reasoning, planning, research synthesis, "
        "multi-step decisions, or substantive questions. Do NOT use when a direct local desktop tool "
        "can simply perform the requested action, such as opening an app, clicking, typing, or changing volume."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "message": {
                "type": "STRING",
                "description": "The user's complete request for R23, preserving important context and constraints."
            },
            "project_context": {
                "type": "STRING",
                "description": "Optional concise local/project context that R23 needs for this request."
            },
            "mode": {
                "type": "STRING",
                "description": "Reasoning mode: auto, fast, max, or apex. Usually auto."
            }
        },
        "required": ["message"]
    },
    "handler": ronn_brain
}
