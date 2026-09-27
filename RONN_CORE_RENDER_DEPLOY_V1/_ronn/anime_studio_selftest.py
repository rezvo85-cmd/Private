"""Deterministic smoke tests for RONN Anime Studio."""
from __future__ import annotations

import os

import anime_studio as studio


def run():
    old_url = os.environ.get("RONN_ANIME_RENDER_URL")
    try:
        os.environ.pop("RONN_ANIME_RENDER_URL", None)

        short = studio.build_plan(
            "Make a 5 second anime fight: Emraan vs Jason, no music, fast punches."
        )
        assert short["shot_count"] == 1, short
        assert short["duration_seconds"] == 5.0, short
        assert short["music_policy"] == "no_music", short
        assert short["characters"][:2] == ["Emraan", "Jason"], short
        assert "same face" in short["character_lock"].lower()
        assert "no giant unintended characters" in short["shots"][0]["negative_prompt"].lower()

        longer = studio.build_plan("Create a 12 second anime opening fight with sound effects only.")
        assert longer["shot_count"] == 3, longer
        assert sum(x["seconds"] for x in longer["shots"]) == 12.0, longer

        blocked = studio.safety_check("make a graphic gore dismemberment anime scene")
        assert blocked["ok"] is False, blocked

        no_backend = studio.run(
            "ci-owner",
            "ci-request",
            "Make a 5 second anime fight: Emraan vs Jason, no music.",
        )
        assert no_backend["planned"] is True, no_backend
        assert no_backend["available"] is False, no_backend
        assert no_backend["reason"] == "render_backend_not_configured", no_backend
        assert no_backend["ready_for_backend"] is True, no_backend
        assert no_backend["quality_gate"]["all_completed"] is False, no_backend

        st = studio.status()
        assert st["enabled"] is True, st
        assert st["large_local_model_required"] is False, st
        assert st["automatic_spend"] is False, st
        assert st["render_backend_configured"] is False, st

        return {
            "ok": True,
            "version": studio.VERSION,
            "short_shots": short["shot_count"],
            "long_shots": longer["shot_count"],
            "backend_safe_when_unconfigured": True,
        }
    finally:
        if old_url is None:
            os.environ.pop("RONN_ANIME_RENDER_URL", None)
        else:
            os.environ["RONN_ANIME_RENDER_URL"] = old_url


if __name__ == "__main__":
    print(run())
