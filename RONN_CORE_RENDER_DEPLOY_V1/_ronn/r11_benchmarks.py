"""Deterministic regression checks for the RONN R11 reliability layer."""
from __future__ import annotations

import time
from r11_intelligence import SIGNAL_COUNT, r11_preflight, r11_directive

def _case(name, fn):
    started=time.time()
    try:
        passed=bool(fn())
        return {"name":name,"passed":passed,"ms":round((time.time()-started)*1000,2),"error":"" if passed else "condition failed"}
    except Exception as exc:
        return {"name":name,"passed":False,"ms":round((time.time()-started)*1000,2),"error":str(exc)[:180]}

def run_r11_benchmarks():
    tests=[
        _case("600 signal registry", lambda: SIGNAL_COUNT == 600),
        _case("simple chat stays fast", lambda: r11_preflight("hi")["route"]["tier"] == "fast"),
        _case("fresh fact uses research", lambda: r11_preflight("what is the latest version available today")["route"]["live_required"]),
        _case("short followup uses history", lambda: r11_preflight("fix it",history=[{"role":"user","content":"the login button is broken"}])["context"]["needs_recent_context"]),
        _case("correction triggers verifier", lambda: r11_preflight("that answer is wrong, recheck and correct yourself")["verification"]["second_pass"]),
        _case("security work escalates", lambda: r11_preflight("debug the authentication token security vulnerability and verify the fix",difficulty=5)["route"]["tier"] in {"deep","apex"}),
        _case("deployment requires runtime proof", lambda: r11_preflight("deploy this server and test the production health check")["verification"]["runtime_proof_for_completion"]),
        _case("project context dependency", lambda: r11_preflight("continue project and keep the same design",history=[{"content":"prior architecture"}],project_context="RONN")["context"]["needs_recent_context"]),
        _case("research requires grounding", lambda: r11_preflight("research this using official sources and citations")["verification"]["must_ground_current_claims"]),
        _case("directive blocks fake completion", lambda: "Do not say code/deployment is fixed" in r11_directive(r11_preflight("debug this broken deployment and verify it"))),
    ]
    passed=sum(1 for t in tests if t["passed"])
    total=len(tests)
    return {"passed":passed,"total":total,"score":round((passed/total)*100 if total else 0,1),"tests":tests}
