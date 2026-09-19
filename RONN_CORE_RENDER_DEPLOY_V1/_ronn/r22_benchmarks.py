"""RONN R22 lean-intelligence architecture checks.

These are deterministic regression tests for routing and prompt-policy behavior.
They do not claim to measure raw model intelligence.
"""
from __future__ import annotations

from r22_lean_core import plan, resolve_route


MODELS = {
    "fast": "openai/gpt-oss-20b",
    "smart": "openai/gpt-oss-120b",
    "creator": "qwen/qwen3.6-27b",
    "vision": "qwen/qwen3.6-27b",
    "live": "groq/compound-mini",
    "research": "groq/compound",
    "nvidia": "nvidia/nemotron-3-super-120b-a12b",
    "or_nemotron": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "or_deepseek": "deepseek/deepseek-v4-flash:free",
    "or_qwen": "qwen/qwen3.8-27b:free",
}


def _case(name, fn):
    try:
        ok = bool(fn())
        return {"name": name, "passed": ok, "error": "" if ok else "condition failed"}
    except Exception as exc:
        return {"name": name, "passed": False, "error": str(exc)[:240]}


def run():
    full = {"groq": True, "nvidia": True, "openrouter": True}

    tests = [
        _case("casual chat stays lightweight", lambda: (
            (lambda d: d["profile"] == "chat" and d["depth"] == "fast"
             and not d["needs_tools"] and not d["second_pass"]
             and not d["use_council"])(plan("yo whats up"))
        )),
        _case("stable knowledge uses main brain", lambda: (
            (lambda d, r: d["profile"] == "knowledge"
             and r[0] == MODELS["smart"]
             and r[1] == "knowledge"
             and not d["use_council"])(
                plan("What causes a solar eclipse?"),
                resolve_route(plan("What causes a solar eclipse?"), full, MODELS),
            )
        )),
        _case("coding uses dedicated specialist", lambda: (
            (lambda d, r: d["profile"] == "coding"
             and r[0] == MODELS["or_deepseek"]
             and r[1] == "creator")(
                plan("Debug this Python API traceback"),
                resolve_route(plan("Debug this Python API traceback"), full, MODELS),
            )
        )),
        _case("current request uses live evidence", lambda: (
            (lambda d: d["needs_live"] and d["profile"] == "research"
             and d["tool_mode"] == "live")(plan("What is the latest AI news today?"))
        )),
        _case("natural nearby request uses live evidence", lambda: (
            (lambda d: d["needs_live"] and d["profile"] == "research")(
                plan("Recommend restaurants near me")
            )
        )),
        _case("vision uses vision specialist", lambda: (
            resolve_route(plan("What is in this image?", has_images=True), full, MODELS)[0]
            == MODELS["or_qwen"]
        )),
        _case("normal deep analysis stays on main brain", lambda: (
            (lambda d, r: d["depth"] in {"smart","deep"}
             and r[0] == MODELS["smart"]
             and not d["use_council"])(
                plan("Compare two database architectures for a medium web app and explain the tradeoffs."),
                resolve_route(
                    plan("Compare two database architectures for a medium web app and explain the tradeoffs."),
                    full,
                    MODELS,
                ),
            )
        )),
        _case("apex reasoning escalates once", lambda: (
            (lambda d, r: d["depth"] == "apex"
             and r[0] == MODELS["or_nemotron"]
             and not d["use_council"])(
                plan(
                    "Design the production architecture for an entire multi-service platform, "
                    "including deployment, database, failure recovery, observability, security, "
                    "multi-step migration, and verify every dependency.",
                    file_names=["a.py","b.py","c.py","d.py"],
                    has_project=True,
                ),
                resolve_route(
                    plan(
                        "Design the production architecture for an entire multi-service platform, "
                        "including deployment, database, failure recovery, observability, security, "
                        "multi-step migration, and verify every dependency.",
                        file_names=["a.py","b.py","c.py","d.py"],
                        has_project=True,
                    ),
                    full,
                    MODELS,
                ),
            )
        )),
        _case("simple prompt policy avoids legacy clutter", lambda: (
            (lambda p: not p["include_tool_directive"]
             and not p["include_long_context_digest"]
             and not p["include_evidence_plan"]
             and not p["include_failure_lessons"]
             and not p["include_verification_directive"]
             and not p["include_tool_catalog"])(
                plan("Tell me a joke")["prompt_policy"]
            )
        )),
        _case("hard verified task gets selective review", lambda: (
            (lambda d: d["verify"]
             and d["prompt_policy"]["include_verification_directive"]
             and d["prompt_policy"]["include_failure_lessons"]
             and not d["use_council"])(
                plan(
                    "Debug this entire production codebase, run tests, make sure there are no errors, "
                    "trace the root cause, verify every dependency, and prepare it to deploy.",
                    file_names=["a.py","b.py","c.py","d.py"],
                    has_project=True,
                )
            )
        )),
        _case("followup keeps conversation context", lambda: (
            plan(
                "do that",
                history=[{"role":"user","content":"Build the API first."},{"role":"assistant","content":"Plan ready."}],
            )["prompt_policy"]["include_long_context_digest"]
        )),
    ]

    passed = sum(1 for x in tests if x["passed"])
    return {
        "passed": passed,
        "total": len(tests),
        "score": round(100 * passed / max(1, len(tests)), 1),
        "tests": tests,
        "scope": "R22 deterministic routing/prompt architecture only; not a raw model-quality score.",
    }


if __name__ == "__main__":
    print(run())
