import time
from cognitive_os import specification_compile, metacognition_state, compile_context
from goal_engine import requirement_ledger, static_code_checks
from tool_system import safe_calculate, validate_json, code_sanity
from intelligence_core import (
    build_task_plan, explicit_requirements, requirement_coverage, answer_audit,
    current_information_risk, domain_risk, ambiguity_scan, task_signature,
)
from task_engine import stats as task_stats
from provider_engine import rank_models


def run_internal_eval():
    tests=[]
    def check(name, fn):
        t=time.time()
        try:
            ok=bool(fn())
            tests.append({"name":name,"passed":ok,"ms":round((time.time()-t)*1000,2)})
        except Exception as e:
            tests.append({"name":name,"passed":False,"error":str(e)[:300],"ms":round((time.time()-t)*1000,2)})

    check("intent_specification",lambda: "website" in specification_compile("Build me a website and keep it responsive.")["goal"].lower())
    check("requirement_ledger",lambda: len(requirement_ledger("Build an app. It must be fast and use local memory."))>=1)
    check("metacognition",lambda: metacognition_state("Research the latest AI model releases","research",5)["budget"]["verification_required"])
    check("context_compiler",lambda: compile_context("database bug","The database has a timeout bug.",[],max_chars=5000)["chars"]>0)
    check("calculator",lambda: safe_calculate("2+3*4")==14)
    check("json_validator",lambda: '"a": 1' in validate_json('{"a":1}'))
    check("python_sanity",lambda: code_sanity("python","def x():\n    return 1")==[])
    check("response_static_check",lambda: static_code_checks("hello")["passed"])
    check("task_plan_verification",lambda: any(p["name"]=="Verify" for p in build_task_plan("Debug this broken API","coding",4)["phases"]))
    check("explicit_requirements",lambda: len(explicit_requirements("Keep the UI red. Do not rename the project."))>=2)
    check("requirement_coverage",lambda: requirement_coverage("Use a red header","The interface uses a red header.")["coverage_signal"]>.5)
    check("time_sensitive_detection",lambda: current_information_risk("What is the latest version today?")["time_sensitive"])
    check("high_stakes_detection",lambda: domain_risk("Give me medical advice about this medication")["high_stakes"])
    check("ambiguity_detection",lambda: ambiguity_scan("fix it")["ambiguous"])
    check("task_signature_stable",lambda: task_signature("Hello   world")==task_signature("hello world"))
    check("answer_audit_completion_boundary",lambda: bool(answer_audit("fix this","I tested and fixed it.",profile="coding",runtime_verified=False)["warnings"]))
    check("task_engine_available",lambda: isinstance(task_stats().get("tasks"),int))
    check("provider_ranking_stable",lambda: set(rank_models(["a","b"]))=={"a","b"})

    passed=sum(1 for x in tests if x["passed"])
    return {
        "passed":passed,
        "total":len(tests),
        "score":round(passed/max(1,len(tests))*100,1),
        "tests":tests,
        "scope":"RONN local architecture/regression tests. These verify deterministic subsystems, not raw model intelligence or external provider quality.",
    }
