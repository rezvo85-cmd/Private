"""RONN Anime Studio capability plane.

Anime Studio is a bounded production helper under R23. It never becomes a
second brain: R23 still owns intent, routing, constraints, and final synthesis.

The module is deliberately provider-agnostic. It can plan production without a
render backend, and can submit jobs to one explicitly configured HTTPS render
endpoint without installing large video models in Core.
"""
from __future__ import annotations

import json
import math
import os
import re
import socket
import uuid
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

VERSION = "RONN-ANIME-STUDIO-1"
MAX_SHOTS = 18
MAX_SHOT_SECONDS = 5.0
DEFAULT_SECONDS = 5.0

_BANNED = (
    "child porn", "cp ", "underage sex", "minor sex", "sexualized minor",
    "suicide tutorial", "self-harm tutorial", "how to hide self harm",
    "graphic dismemberment", "graphic gore",
)

_BEATS = (
    "establish the setting and instantly create tension",
    "rapid approach with aggressive camera tracking",
    "close-range exchange with clean readable choreography",
    "counterattack with a sharp impact pause",
    "supernatural power reveal close to the fighter",
    "fast barrage with controlled motion trails",
    "defensive reversal and camera whip",
    "environmental impact with dust and debris",
    "close-up reaction and immediate re-engagement",
    "high-speed clash with a low-angle camera",
    "brief power escalation without changing character design",
    "finishing exchange with a strong silhouette",
    "aftermath beat with drifting debris",
    "final stare-down and freeze-frame composition",
)


def _clean(text: Any, limit: int = 8000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _seconds(message: str) -> float:
    low = str(message or "").lower()
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b", low)
    if m:
        return max(1.0, min(float(m.group(1)), 90.0))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)\b", low)
    if m:
        return max(1.0, min(float(m.group(1)) * 60.0, 90.0))
    return DEFAULT_SECONDS


def _music_policy(message: str) -> str:
    low = str(message or "").lower()
    if any(x in low for x in ("no music", "without music", "no background music", "no song")):
        return "no_music"
    if any(x in low for x in ("music", "song", "soundtrack")):
        return "music_requested"
    return "sound_effects_only"


def _extract_names(message: str) -> list[str]:
    raw = _clean(message, 4000)
    names: list[str] = []

    def add(name: str):
        name = re.sub(r"[^A-Za-z0-9 _'’-]", "", name).strip()
        if not name or len(name) > 48:
            return
        if name.lower() in {
            "anime", "jojo", "fight", "opening", "stand", "video", "scene",
            "make", "create", "generate", "versus", "vs",
        }:
            return
        if name not in names:
            names.append(name)

    for pat in (
        r"\b([A-Z][A-Za-z0-9'’-]{1,30})\s+(?:vs\.?|versus)\s+([A-Z][A-Za-z0-9'’-]{1,30})\b",
        r"\bbetween\s+([A-Z][A-Za-z0-9'’-]{1,30})\s+and\s+([A-Z][A-Za-z0-9'’-]{1,30})\b",
    ):
        m = re.search(pat, raw)
        if m:
            add(m.group(1))
            add(m.group(2))

    # If no explicit matchup is present, preserve only a few likely proper names.
    if not names:
        for token in re.findall(r"\b[A-Z][a-z][A-Za-z0-9'’-]{1,30}\b", raw):
            add(token)
            if len(names) >= 4:
                break
    return names[:8]


def safety_check(message: str) -> dict[str, Any]:
    low = " " + _clean(message, 12000).lower() + " "
    hit = next((x for x in _BANNED if x in low), "")
    return {
        "ok": not bool(hit),
        "reason": "blocked_unsafe_generation_request" if hit else "",
        "matched": hit,
    }


def build_plan(message: str, files=None) -> dict[str, Any]:
    """Create a deterministic production plan that a renderer can execute.

    This function does not pretend to render anything. It creates consistent,
    bounded shot prompts and continuity metadata from the user's request.
    """
    message = _clean(message, 12000)
    duration = _seconds(message)
    shot_count = max(1, min(MAX_SHOTS, int(math.ceil(duration / MAX_SHOT_SECONDS))))
    remaining = duration
    names = _extract_names(message)
    music = _music_policy(message)

    reference_names = []
    for item in list(files or [])[:24]:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
        else:
            name = str(getattr(item, "name", "") or "")
        if name:
            reference_names.append(name[:180])

    character_lock = (
        "Keep every named character visually identical across shots: same face, hair, "
        "skin tone, outfit, body proportions, accessories, aura colors, and scale. "
        "Humanoid spirit companions must remain human-sized unless the request explicitly "
        "says otherwise. Never merge characters or swap clothing."
    )
    style_lock = (
        "High-quality 2D cel-shaded supernatural battle anime, strong silhouettes, "
        "bold posing, crisp linework, dramatic high-contrast lighting, readable anatomy, "
        "fast but coherent choreography, intentional smear frames, impact frames, speed "
        "lines, cinematic camera motion, and consistent character design. Avoid generic "
        "3D-plastic motion and avoid slow floating movement."
    )
    negative = (
        "no giant unintended characters, no duplicated limbs, no fused bodies, no face "
        "morphing, no outfit changes, no random text, no logo, no watermark, no broken "
        "hands, no extra fingers, no camera teleporting, no unrelated characters, "
        "no graphic gore"
    )

    shots = []
    for i in range(shot_count):
        seconds = round(min(MAX_SHOT_SECONDS, remaining), 2)
        remaining = max(0.0, remaining - seconds)
        beat = _BEATS[min(i, len(_BEATS) - 1)]
        continuity_in = "start from the established character lock and setting"
        if i:
            continuity_in = f"continue directly from shot {i}; preserve positions, damage-free appearance, lighting, and motion direction"
        continuity_out = (
            "end on a stable readable pose or motion direction that can seed the next shot"
            if i < shot_count - 1
            else "end on a decisive readable final composition"
        )
        sound = [
            "cloth movement",
            "footsteps or movement whooshes",
            "clean punch/impact sounds",
            "energy crackle when supernatural power appears",
            "environmental debris sounds",
        ]
        if music == "no_music":
            sound.insert(0, "absolutely no music or song")
        elif music == "sound_effects_only":
            sound.insert(0, "sound effects only; no background song")

        prompt = (
            f"{message}. SHOT {i+1}/{shot_count}, about {seconds:g} seconds: {beat}. "
            f"{style_lock} {character_lock} Continuity: {continuity_in}; {continuity_out}. "
            f"Sound: {', '.join(sound)}. Negative constraints: {negative}."
        )
        shots.append({
            "index": i + 1,
            "seconds": seconds,
            "beat": beat,
            "prompt": prompt[:10000],
            "negative_prompt": negative,
            "continuity_in": continuity_in,
            "continuity_out": continuity_out,
            "sound_fx": sound,
            "references": reference_names,
        })

    return {
        "version": VERSION,
        "title": "RONN Anime Studio Project",
        "source_request": message,
        "duration_seconds": round(duration, 2),
        "shot_count": len(shots),
        "max_shot_seconds": MAX_SHOT_SECONDS,
        "characters": names,
        "character_lock": character_lock,
        "style_lock": style_lock,
        "music_policy": music,
        "reference_files": reference_names,
        "shots": shots,
        "postprocess": {
            "stitch_in_order": True,
            "match_last_frame_to_next_shot": True,
            "frame_interpolation": "optional_after_generation",
            "upscale": "optional_after_generation",
            "preserve_original_audio": True,
        },
    }


def _configured_endpoint() -> str:
    return (os.getenv("RONN_ANIME_RENDER_URL") or "").strip()


def _endpoint_allowed(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid_url"
    if parsed.scheme != "https" or not parsed.hostname:
        return False, "https_required"
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False, "local_endpoint_not_allowed"
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        for info in infos:
            ip = ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "private_endpoint_not_allowed"
    except Exception:
        # DNS can be unavailable in CI. The actual request still fails closed.
        pass
    return True, ""


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RONN-Anime-Studio/1",
    }
    token = (os.getenv("RONN_ANIME_RENDER_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=max(5.0, min(float(timeout), 120.0))) as resp:
            body = resp.read(2_000_000)
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        body = exc.read(200_000)
        return {
            "ok": False,
            "reason": "render_http_error",
            "status_code": int(exc.code),
            "detail": body.decode("utf-8", "replace")[:1000],
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "reason": "render_connection_error",
            "detail": exc.__class__.__name__,
        }

    if status < 200 or status >= 300:
        return {"ok": False, "reason": "render_http_error", "status_code": status}
    try:
        value = json.loads(body.decode("utf-8"))
    except Exception:
        return {"ok": False, "reason": "render_invalid_json"}
    if not isinstance(value, dict):
        return {"ok": False, "reason": "render_invalid_response"}
    return value


def _normalize_job(result: dict[str, Any], shot_index: int) -> dict[str, Any]:
    result = result or {}
    status = str(result.get("status") or ("complete" if result.get("output_url") else "")).lower()
    submitted = bool(
        result.get("ok", True)
        and (result.get("job_id") or result.get("output_url") or status in {"queued", "submitted", "running", "complete", "completed"})
    )
    completed = bool(
        result.get("ok", True)
        and (result.get("output_url") or status in {"complete", "completed", "succeeded", "success"})
    )
    return {
        "shot_index": shot_index,
        "ok": bool(result.get("ok", submitted)),
        "submitted": submitted,
        "completed": completed,
        "status": status or ("submitted" if submitted else "failed"),
        "job_id": str(result.get("job_id") or "")[:240],
        "output_url": str(result.get("output_url") or "")[:2000],
        "preview_url": str(result.get("preview_url") or "")[:2000],
        "provider": str(result.get("provider") or os.getenv("RONN_ANIME_PROVIDER_NAME") or "configured_remote")[:120],
        "quality": result.get("quality") if isinstance(result.get("quality"), dict) else {},
        "reason": str(result.get("reason") or result.get("error") or "")[:500],
    }


def quality_gate(plan: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    jobs = list(jobs or [])
    required = int(plan.get("shot_count") or 0)
    submitted = sum(1 for x in jobs if x.get("submitted"))
    completed = sum(1 for x in jobs if x.get("completed"))
    outputs = sum(1 for x in jobs if x.get("output_url"))
    return {
        "planned_shots": required,
        "submitted_shots": submitted,
        "completed_shots": completed,
        "output_shots": outputs,
        "all_submitted": bool(required and submitted == required),
        "all_completed": bool(required and completed == required and outputs == required),
        "verified_visual_quality": False,
        "note": (
            "Completion is based only on renderer job/output evidence. Visual quality is not "
            "claimed verified unless a future frame-judge backend actually inspects the output."
        ),
    }


def run(owner: str, request_id: str, message: str, files=None, *, depth: str = "smart",
        checkpoint_fn=None) -> dict[str, Any]:
    safe = safety_check(message)
    plan = build_plan(message, files)
    result: dict[str, Any] = {
        "version": VERSION,
        "ok": False,
        "available": False,
        "planned": True,
        "submitted": False,
        "completed": False,
        "request_id": str(request_id or uuid.uuid4().hex),
        "owner_scoped": bool(owner),
        "plan": plan,
        "jobs": [],
        "quality_gate": {},
        "reason": "",
    }

    if not safe.get("ok"):
        result["reason"] = safe.get("reason")
        result["safety"] = safe
        return result

    endpoint = _configured_endpoint()
    if not endpoint:
        result["reason"] = "render_backend_not_configured"
        result["ready_for_backend"] = True
        result["quality_gate"] = quality_gate(plan, [])
        return result

    allowed, why = _endpoint_allowed(endpoint)
    if not allowed:
        result["reason"] = why
        result["quality_gate"] = quality_gate(plan, [])
        return result

    result["available"] = True
    if checkpoint_fn:
        try:
            checkpoint_fn("Anime Studio", "started", f"Submitting {plan['shot_count']} bounded anime shot(s).")
        except Exception:
            pass

    timeout = float(os.getenv("RONN_ANIME_RENDER_TIMEOUT") or "60")
    max_render = max(1, min(int(os.getenv("RONN_ANIME_MAX_SHOTS_PER_TURN") or str(MAX_SHOTS)), MAX_SHOTS))
    jobs = []
    for shot in plan["shots"][:max_render]:
        payload = {
            "request_id": result["request_id"],
            "owner": str(owner or "")[:160],
            "mode": "anime_video",
            "depth": str(depth or "smart"),
            "project": {
                "duration_seconds": plan["duration_seconds"],
                "shot_count": plan["shot_count"],
                "characters": plan["characters"],
                "character_lock": plan["character_lock"],
                "style_lock": plan["style_lock"],
                "music_policy": plan["music_policy"],
                "reference_files": plan["reference_files"],
            },
            "shot": shot,
        }
        raw = _post_json(endpoint, payload, timeout)
        job = _normalize_job(raw, int(shot["index"]))
        jobs.append(job)
        if checkpoint_fn:
            try:
                checkpoint_fn(
                    "Anime Studio",
                    "complete" if job.get("submitted") else "blocked",
                    f"Shot {shot['index']}: {job.get('status') or job.get('reason') or 'unknown'}",
                )
            except Exception:
                pass

    if len(plan["shots"]) > max_render:
        result["reason"] = "per_turn_render_limit"
    result["jobs"] = jobs
    gate = quality_gate(plan, jobs)
    result["quality_gate"] = gate
    result["submitted"] = bool(gate["all_submitted"])
    result["completed"] = bool(gate["all_completed"])
    result["ok"] = bool(result["submitted"])
    if not result["reason"] and not result["ok"]:
        result["reason"] = "render_submission_incomplete"
    return result


def status() -> dict[str, Any]:
    endpoint = _configured_endpoint()
    allowed, reason = _endpoint_allowed(endpoint) if endpoint else (False, "not_configured")
    return {
        "version": VERSION,
        "enabled": True,
        "architecture": "R23-owned capability plane",
        "large_local_model_required": False,
        "provider_agnostic": True,
        "render_backend_configured": bool(endpoint and allowed),
        "render_backend_reason": "" if endpoint and allowed else reason,
        "max_shots": MAX_SHOTS,
        "max_shot_seconds": MAX_SHOT_SECONDS,
        "character_lock": True,
        "style_lock": True,
        "storyboard_plan": True,
        "fight_choreography_beats": True,
        "continuity_plan": True,
        "sound_fx_plan": True,
        "no_music_mode": True,
        "quality_evidence_gate": True,
        "bounded_remote_submission": True,
        "automatic_spend": False,
    }
