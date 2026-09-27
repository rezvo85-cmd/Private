"""Hugging Face ZeroGPU renderer for RONN Anime Studio.

This module is a bounded execution backend. It does not plan or route tasks.
R23/Anime Studio create the plan; this module only turns approved shots into
cloud-rendered assets using public Gradio Spaces. No video-model weights are
installed in RONN Core.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

VERSION = "RONN-ANIME-HF-1"

DEFAULT_IMAGE_SPACE = "mrfakename/Z-Image-Turbo"
DEFAULT_VIDEO_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"

BASE = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE / "data" / "anime_outputs"
REFERENCE_ROOT = BASE / "data" / "anime_refs"
TEMP_ROOT = BASE / "data" / "anime_tmp"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

MAX_OUTPUTS_PER_OWNER = max(4, min(60, int(os.getenv("RONN_ANIME_MAX_OUTPUTS_PER_OWNER", "16") or "16")))
DEFAULT_JOB_TIMEOUT = max(90.0, min(900.0, float(os.getenv("RONN_ANIME_HF_JOB_TIMEOUT", "420") or "420")))
MAX_RENDER_SHOTS = max(1, min(6, int(os.getenv("RONN_ANIME_HF_MAX_SHOTS", "2") or "2")))


def _safe_owner(owner: str) -> str:
    raw = str(owner or "anonymous")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def owner_output_dir(owner: str) -> Path:
    path = OUTPUT_ROOT / _safe_owner(owner)
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_reference_images(owner: str, request_id: str, images: list[str]) -> list[str]:
    """Persist a few user-provided data-URL images for the background render job."""
    root=REFERENCE_ROOT/_safe_owner(owner)
    root.mkdir(parents=True,exist_ok=True)
    request=re.sub(r"[^A-Za-z0-9_-]","",str(request_id or ""))[-32:] or "request"
    saved=[]
    for idx,raw in enumerate(list(images or [])[:4],start=1):
        text=str(raw or "")
        m=re.match(r"^data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\r\n]+)$",text,re.I)
        if not m:
            continue
        ext="jpg" if m.group(1).lower() in {"jpeg","jpg"} else m.group(1).lower()
        try:
            data=base64.b64decode(m.group(2),validate=True)
        except Exception:
            continue
        if not data or len(data)>20*1024*1024:
            continue
        path=root/f"{request}_{idx}.{ext}"
        path.write_bytes(data)
        saved.append(str(path))
    # Bound retained references; they are only working inputs for generation.
    rows=sorted([p for p in root.iterdir() if p.is_file()],key=lambda p:p.stat().st_mtime,reverse=True)
    for p in rows[20:]:
        try:p.unlink()
        except Exception:pass
    return saved


def resolve_output_path(owner: str, filename: str) -> Path | None:
    raw=str(filename or "")
    name=Path(raw).name
    if raw != name or "/" in raw or "\\" in raw:
        return None
    if not name or not re.fullmatch(r"[A-Za-z0-9_.-]{8,180}\.mp4", name):
        return None
    root = owner_output_dir(owner).resolve()
    path = (root / name).resolve()
    if root not in path.parents:
        return None
    if not path.is_file():
        return None
    return path


def _cleanup_owner(owner: str):
    root = owner_output_dir(owner)
    rows = sorted(
        [p for p in root.glob("*.mp4") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in rows[MAX_OUTPUTS_PER_OWNER:]:
        try:
            p.unlink()
        except Exception:
            pass


def _gradio():
    try:
        from gradio_client import Client, handle_file
    except Exception as exc:
        raise RuntimeError("gradio_client_unavailable") from exc
    return Client, handle_file


def _token() -> str | None:
    value = (
        os.getenv("RONN_ANIME_HF_TOKEN")
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
        or ""
    ).strip()
    return value or None


def _client(space: str):
    Client, _ = _gradio()
    kwargs: dict[str, Any] = {
        "src": space,
        "verbose": False,
        "download_files": str(TEMP_ROOT),
        "max_workers": 2,
        "httpx_kwargs": {"timeout": 45.0},
    }
    tok = _token()
    if tok:
        kwargs["token"] = tok
    return Client(**kwargs)


def _named_endpoint(client, preferred: str) -> str:
    """Prefer the expected endpoint, then discover a matching generate endpoint."""
    try:
        info = client.view_api(return_format="dict")
        named = (info or {}).get("named_endpoints") or {}
        if preferred in named:
            return preferred
        target = preferred.strip("/").lower()
        for name in named:
            low = str(name).strip("/").lower()
            if target in low:
                return str(name)
        for name in named:
            if "generate" in str(name).lower():
                return str(name)
    except Exception:
        pass
    return preferred


def _path_from_result(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        return _path_from_result(value[0])
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("path", "url", "name"):
            if value.get(key):
                return str(value[key])
    for attr in ("path", "url", "name"):
        v = getattr(value, attr, None)
        if v:
            return str(v)
    return ""


def _submit_result(client, args: list[Any], *, api_name: str, timeout: float) -> Any:
    endpoint = _named_endpoint(client, api_name)
    job = client.submit(*args, api_name=endpoint)
    try:
        return job.result(timeout=timeout)
    except TimeoutError:
        try:
            job.cancel()
        except Exception:
            pass
        raise RuntimeError("hf_zero_job_timeout")


def _keyframe_prompt(shot: dict[str, Any]) -> str:
    raw = str(shot.get("prompt") or "")
    return (
        raw[:7000]
        + " Single clean opening keyframe for animation. Preserve exact character identity, "
          "outfit, proportions, aura colors, and human-sized supernatural companions. "
          "Sharp 2D cel-shaded anime illustration, readable anatomy, no text, no watermark."
    )[:8000]


def generate_keyframe(shot: dict[str, Any], *, timeout: float = DEFAULT_JOB_TIMEOUT) -> dict[str, Any]:
    space = (os.getenv("RONN_ANIME_HF_IMAGE_SPACE") or DEFAULT_IMAGE_SPACE).strip()
    client = _client(space)
    seed = int(shot.get("seed") or 42) % (2**31 - 1)
    result = _submit_result(
        client,
        [
            _keyframe_prompt(shot),
            512,
            896,
            9,
            seed,
            False,
        ],
        api_name="/generate_image",
        timeout=timeout,
    )
    path = _path_from_result(result)
    if not path:
        raise RuntimeError("hf_keyframe_missing_output")
    return {
        "ok": True,
        "provider": "huggingface_zero",
        "space": space,
        "path": path,
        "seed": seed,
    }


def generate_video(keyframe_path: str, shot: dict[str, Any], *, timeout: float = DEFAULT_JOB_TIMEOUT) -> dict[str, Any]:
    space = (os.getenv("RONN_ANIME_HF_VIDEO_SPACE") or DEFAULT_VIDEO_SPACE).strip()
    client = _client(space)
    _, handle_file = _gradio()
    duration = max(0.5, min(float(shot.get("seconds") or 5.0), 5.0))
    seed = int(shot.get("seed") or 42) % (2**31 - 1)
    prompt = str(shot.get("prompt") or "")[:9000]
    negative = str(shot.get("negative_prompt") or "")[:4000]
    result = _submit_result(
        client,
        [
            handle_file(keyframe_path),
            prompt,
            6,
            negative,
            duration,
            1.0,
            1.0,
            seed,
            False,
        ],
        api_name="/generate_video",
        timeout=timeout,
    )
    path = _path_from_result(result)
    if not path:
        raise RuntimeError("hf_video_missing_output")
    return {
        "ok": True,
        "provider": "huggingface_zero",
        "space": space,
        "path": path,
        "seed": seed,
        "duration_seconds": duration,
    }


def _save_video(owner: str, request_id: str, shot_index: int, source_path: str) -> dict[str, Any]:
    src = Path(source_path)
    if not src.is_file():
        raise RuntimeError("renderer_output_file_missing")
    clean_request = re.sub(r"[^A-Za-z0-9_-]", "", str(request_id or ""))[-32:] or hashlib.sha256(
        str(time.time_ns()).encode()
    ).hexdigest()[:16]
    filename = f"{clean_request}_s{int(shot_index):02d}_{int(time.time())}.mp4"
    target = owner_output_dir(owner) / filename
    shutil.copy2(src, target)
    _cleanup_owner(owner)
    return {
        "filename": filename,
        "path": str(target),
        "output_url": "/api/anime/output/" + filename,
        "bytes": int(target.stat().st_size),
    }


def render_project(payload: dict[str, Any], progress_cb=None) -> dict[str, Any]:
    """Render the approved Anime Studio project in a background RONN job."""
    owner = str(payload.get("owner") or "")
    request_id = str(payload.get("request_id") or "")
    plan = payload.get("plan") or {}
    shots = list(plan.get("shots") or [])[:MAX_RENDER_SHOTS]
    if not shots:
        raise RuntimeError("anime_plan_has_no_shots")

    outputs = []
    total = len(shots)
    for idx, shot in enumerate(shots, start=1):
        if progress_cb:
            progress_cb(5 + int((idx - 1) / max(total, 1) * 80))
        reference_paths=[str(x) for x in (payload.get("reference_paths") or []) if str(x)]
        reference=next((x for x in reference_paths if Path(x).is_file()),"")
        if reference:
            keyframe={
                "ok":True,
                "provider":"user_reference",
                "space":"",
                "path":reference,
                "seed":int(shot.get("seed") or 42),
            }
        else:
            keyframe = generate_keyframe(shot)
        if progress_cb:
            progress_cb(20 + int((idx - 1) / max(total, 1) * 70))
        video = generate_video(keyframe["path"], shot)
        saved = _save_video(owner, request_id, int(shot.get("index") or idx), video["path"])
        outputs.append({
            "shot_index": int(shot.get("index") or idx),
            "provider": "huggingface_zero",
            "image_space": keyframe.get("space") or "",
            "reference_used": bool(reference),
            "video_space": video["space"],
            "duration_seconds": video["duration_seconds"],
            "seed": video["seed"],
            **saved,
        })
        if progress_cb:
            progress_cb(10 + int(idx / max(total, 1) * 85))

    return {
        "ok": bool(outputs),
        "provider": "huggingface_zero",
        "requested_shots": int(plan.get("shot_count") or len(shots)),
        "rendered_shots": len(outputs),
        "limited_to": MAX_RENDER_SHOTS,
        "outputs": outputs,
        "complete_project": bool(len(outputs) == int(plan.get("shot_count") or len(outputs))),
        "rate_limit_note": (
            "Public ZeroGPU is free but shared and may queue or rate-limit. "
            "A Hugging Face token can be supplied through RONN_ANIME_HF_TOKEN for account-scoped quota."
        ),
    }


def status() -> dict[str, Any]:
    try:
        import gradio_client  # noqa: F401
        installed = True
    except Exception:
        installed = False
    return {
        "version": VERSION,
        "installed": installed,
        "provider": "huggingface_zero",
        "image_space": (os.getenv("RONN_ANIME_HF_IMAGE_SPACE") or DEFAULT_IMAGE_SPACE).strip(),
        "video_space": (os.getenv("RONN_ANIME_HF_VIDEO_SPACE") or DEFAULT_VIDEO_SPACE).strip(),
        "token_configured": bool(_token()),
        "large_local_model_required": False,
        "automatic_paid_spend": False,
        "shared_free_gpu": True,
        "reference_image_to_video": True,
        "max_render_shots_per_job": MAX_RENDER_SHOTS,
        "output_retention_per_owner": MAX_OUTPUTS_PER_OWNER,
    }
