"""Deterministic regression checks for RONN R12 improvement engine."""
from __future__ import annotations
import time
from r12_improvements import IMPROVEMENT_COUNT, r12_preflight, r12_directive

def _case(name, fn):
    t=time.time()
    try:
        ok=bool(fn())
        return {"name":name,"passed":ok,"ms":round((time.time()-t)*1000,2),"error":"" if ok else "condition failed"}
    except Exception as exc:
        return {"name":name,"passed":False,"ms":round((time.time()-t)*1000,2),"error":str(exc)[:180]}

def run_r12_benchmarks():
    tests=[
        _case("400 improvement registry", lambda: IMPROVEMENT_COUNT == 400),
        _case("mobile request activates mobile policy", lambda: "mobile" in r12_preflight("fix the iphone mobile screen zoom")["active_domains"]),
        _case("debug request activates debugging", lambda: "debugging" in r12_preflight("this error is broken fix the root cause")["active_domains"]),
        _case("research request activates research", lambda: "research" in r12_preflight("research the latest version using official sources")["active_domains"]),
        _case("privacy request activates privacy", lambda: "privacy" in r12_preflight("keep my api key secret and private")["active_domains"]),
        _case("project context activates projects", lambda: "projects" in r12_preflight("continue this build",project_context="RONN")["active_domains"]),
        _case("hard task raises quality", lambda: r12_preflight("verify and prove this difficult system fix",difficulty=6)["quality_floor"]=="high"),
        _case("directive references registry", lambda: "400 active policies" in r12_directive(r12_preflight("improve quality and verify it"))),
    ]
    passed=sum(1 for t in tests if t["passed"])
    total=len(tests)
    return {"passed":passed,"total":total,"score":round((passed/total)*100 if total else 0,1),"tests":tests}
