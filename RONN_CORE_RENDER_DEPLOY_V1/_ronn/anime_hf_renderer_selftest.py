"""Deterministic non-network checks for RONN's Hugging Face Anime renderer."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import anime_hf_renderer as renderer


def run():
    old_root=renderer.OUTPUT_ROOT
    old_reference=renderer.REFERENCE_ROOT
    old_temp=renderer.TEMP_ROOT
    old_image=os.environ.get("RONN_ANIME_HF_IMAGE_SPACE")
    old_video=os.environ.get("RONN_ANIME_HF_VIDEO_SPACE")
    try:
        with tempfile.TemporaryDirectory(prefix="ronn-anime-ci-") as td:
            root=Path(td)
            renderer.OUTPUT_ROOT=root/"outputs"
            renderer.REFERENCE_ROOT=root/"refs"
            renderer.TEMP_ROOT=root/"tmp"
            renderer.OUTPUT_ROOT.mkdir(parents=True,exist_ok=True)
            renderer.REFERENCE_ROOT.mkdir(parents=True,exist_ok=True)
            renderer.TEMP_ROOT.mkdir(parents=True,exist_ok=True)

            owner_a="ci-owner-a"
            owner_b="ci-owner-b"

            # User reference images are accepted only as bounded image data URLs
            # and are owner-scoped working inputs.
            tiny_png="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            refs=renderer.store_reference_images(owner_a,"ci-request",[tiny_png])
            assert len(refs)==1 and Path(refs[0]).is_file(), refs
            assert renderer._safe_owner(owner_a) in refs[0], refs
            source=root/"source.mp4"
            source.write_bytes(b"RONN_FAKE_MP4_FOR_PATH_TEST")

            saved=renderer._save_video(owner_a,"ci-request",1,str(source))
            assert saved["filename"].endswith(".mp4"), saved
            assert saved["output_url"].startswith("/api/anime/output/"), saved
            assert renderer.resolve_output_path(owner_a,saved["filename"]) is not None
            assert renderer.resolve_output_path(owner_b,saved["filename"]) is None
            assert renderer.resolve_output_path(owner_a,"../"+saved["filename"]) is None
            assert renderer.resolve_output_path(owner_a,"not-a-video.txt") is None

            prompt=renderer._keyframe_prompt({
                "prompt":"Emraan vs Jason, high-quality 2D anime fight.",
            })
            assert "opening keyframe" in prompt.lower()
            assert "no text" in prompt.lower()

            st=renderer.status()
            assert st["large_local_model_required"] is False, st
            assert st["automatic_paid_spend"] is False, st
            assert st["shared_free_gpu"] is True, st
            assert st["max_render_shots_per_job"] >= 1, st

            return {
                "ok":True,
                "version":renderer.VERSION,
                "owner_output_isolation":True,
                "no_local_video_weights":True,
                "automatic_paid_spend":False,
            }
    finally:
        renderer.OUTPUT_ROOT=old_root
        renderer.REFERENCE_ROOT=old_reference
        renderer.TEMP_ROOT=old_temp
        if old_image is None:
            os.environ.pop("RONN_ANIME_HF_IMAGE_SPACE",None)
        else:
            os.environ["RONN_ANIME_HF_IMAGE_SPACE"]=old_image
        if old_video is None:
            os.environ.pop("RONN_ANIME_HF_VIDEO_SPACE",None)
        else:
            os.environ["RONN_ANIME_HF_VIDEO_SPACE"]=old_video


if __name__=="__main__":
    print(run())
