"""DeepEval adapter for RONN's evaluation plane.

DeepEval is deliberately evaluation-only. Production chat does not import the
package. R23 keeps ownership of routing, planning, confidence, and final answers.
"""
from __future__ import annotations

import json
from importlib.util import find_spec
from typing import Any

VERSION = "R23-DEEPEVAL-ADAPTER-1"


def available() -> bool:
    return find_spec("deepeval") is not None


def status() -> dict[str, Any]:
    return {
        "version": VERSION,
        "installed": available(),
        "scope": "evaluation_only",
        "production_chat_dependency": False,
        "owns_routing": False,
        "owns_brain": False,
    }


def build_test_cases(records: list[dict[str, Any]]):
    """Convert RONN eval rows into DeepEval LLMTestCase objects.

    No evaluation model is invoked here. This is the stable bridge used by
    offline/CI eval jobs and future explicit live evaluation runs.
    """
    if not available():
        raise RuntimeError("DeepEval is not installed in this environment.")
    from deepeval.test_case import LLMTestCase

    cases = []
    for row in records or []:
        inp = str(row.get("input") or "")
        actual = str(row.get("actual_output") or "")
        expected = row.get("expected_output")
        kwargs = {"input": inp, "actual_output": actual}
        if expected is not None:
            kwargs["expected_output"] = str(expected)
        retrieval = row.get("retrieval_context")
        if isinstance(retrieval, list):
            kwargs["retrieval_context"] = [str(x) for x in retrieval]
        cases.append(LLMTestCase(**kwargs))
    return cases


def run_non_llm_smoke() -> dict[str, Any]:
    """Exercise current DeepEval without a network call or judge model.

    The smoke is intentionally deterministic; subjective RONN quality remains
    measured by R23's existing evaluation lab unless an explicit live eval run
    is requested.
    """
    if not available():
        return {"ok": False, "score": 0.0, "reason": "deepeval_not_installed"}

    from deepeval.metrics import ExactMatchMetric, PatternMatchMetric

    rows = [
        {
            "input": "Return the R23 owner name.",
            "actual_output": "r23_brain.py",
            "expected_output": "r23_brain.py",
        },
        {
            "input": "Return a JSON status object.",
            "actual_output": json.dumps({"r23": True, "main_brain": "single"}),
        },
    ]
    cases = build_test_cases(rows)

    exact = ExactMatchMetric(threshold=1.0)
    exact_score = float(exact.measure(cases[0]) or 0.0)

    pattern = PatternMatchMetric(pattern=r'^\{.*"r23"\s*:\s*true.*\}$')
    pattern_score = float(pattern.measure(cases[1]) or 0.0)

    tests = [
        {"name": "deepeval_exact_match", "passed": exact_score >= 1.0, "score": exact_score},
        {"name": "deepeval_pattern_match", "passed": pattern_score >= 1.0, "score": pattern_score},
    ]
    passed = sum(1 for x in tests if x["passed"])
    return {
        "ok": passed == len(tests),
        "passed": passed,
        "total": len(tests),
        "score": round((passed / max(1, len(tests))) * 100.0, 1),
        "tests": tests,
        "scope": "DeepEval package/integration smoke; no LLM-as-a-judge call.",
    }


def build_live_eval_cases(records: list[dict[str, Any]]):
    """Explicit bridge for later/live quality runs.

    This does not run automatically and therefore cannot silently change R23.
    Callers may attach DeepEval metrics such as answer relevancy or faithfulness
    using their chosen evaluator model.
    """
    return build_test_cases(records)


if __name__ == "__main__":
    print(json.dumps({"status": status(), "smoke": run_non_llm_smoke()}, indent=2))
