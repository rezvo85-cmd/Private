"""Deterministic R13 ensemble regression checks."""
from __future__ import annotations
import time
from r13_ensemble import (
    NEMOTRON_MODEL, DEEPSEEK_MODEL, QWEN_MODEL, CRITIC_MODEL,
    ENSEMBLE_MODELS, choose_primary, council_models, fallback_models
)

def _case(name, fn):
    t=time.time()
    try:
        ok=bool(fn())
        return {"name":name,"passed":ok,"ms":round((time.time()-t)*1000,2),"error":"" if ok else "condition failed"}
    except Exception as exc:
        return {"name":name,"passed":False,"ms":round((time.time()-t)*1000,2),"error":str(exc)[:180]}

def run_r13_benchmarks():
    tests=[
        _case("four model ensemble", lambda: len(ENSEMBLE_MODELS)==4),
        _case("reasoning specialist", lambda: choose_primary("analysis",5)[0]==NEMOTRON_MODEL),
        _case("coding specialist", lambda: choose_primary("coding",3)[0]==DEEPSEEK_MODEL),
        _case("vision specialist", lambda: choose_primary("chat",1,True)[0]==QWEN_MODEL),
        _case("general specialist", lambda: choose_primary("chat",1)[0]==QWEN_MODEL),
        _case("critic is independent", lambda: CRITIC_MODEL not in council_models("coding")),
        _case("coding council is diverse", lambda: council_models("coding")==[NEMOTRON_MODEL,DEEPSEEK_MODEL]),
        _case("general council is diverse", lambda: council_models("chat")==[NEMOTRON_MODEL,QWEN_MODEL]),
        _case("fallback includes critic", lambda: CRITIC_MODEL in fallback_models("chat")),
    ]
    passed=sum(1 for t in tests if t["passed"])
    total=len(tests)
    return {"passed":passed,"total":total,"score":round((passed/total)*100 if total else 0,1),"tests":tests}
