"""RONN R23 live Brain Arena.

Small, objective, model-agnostic checks measure instruction following, arithmetic,
logic, and coding syntax. Results only influence routing when every configured
main-brain candidate has enough fresh samples. Transport failures are not treated
as wrong answers; provider health handles reliability separately.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from project_brain import model_arena, set_model_score

VERSION="R23-BRAIN-ARENA-2"
MIN_SAMPLES=8
DOMAIN_MIN_SAMPLES={"instruction":2,"reasoning":3,"coding":3}
MAX_AGE_DAYS=14
RUN_TTL_SECONDS=7*24*3600
RETRY_COOLDOWN_SECONDS=6*3600

_LOCK=threading.Lock()
_LAST_ATTEMPT=0.0

CASES=(
    {
        "id":"instruction_exact",
        "domain":"instruction",
        "prompt":"Reply with exactly this text and nothing else: RONN_ARENA_7",
        "expected":"RONN_ARENA_7",
        "kind":"exact",
        "max_tokens":32,
    },
    {
        "id":"instruction_order",
        "domain":"instruction",
        "prompt":"Sort these letters alphabetically and reply with only the comma-separated result: z,a,m",
        "expected":"a,m,z",
        "kind":"exact",
        "max_tokens":32,
    },
    {
        "id":"arithmetic_exact",
        "domain":"reasoning",
        "prompt":"Compute (37 * 24) - 11. Reply with only the integer.",
        "expected":"877",
        "kind":"exact",
        "max_tokens":48,
    },
    {
        "id":"logic_exact",
        "domain":"reasoning",
        "prompt":"Every K is an M. No M is a Z. Can any K be a Z? Reply with only YES or NO.",
        "expected":"NO",
        "kind":"casefold_exact",
        "max_tokens":48,
    },
    {
        "id":"sequence_exact",
        "domain":"reasoning",
        "prompt":"What is the next number in this sequence: 2, 6, 12, 20, 30, ? Reply with only the integer.",
        "expected":"42",
        "kind":"exact",
        "max_tokens":48,
    },
    {
        "id":"python_slice",
        "domain":"coding",
        "prompt":"In Python, give one expression that returns the last 3 characters of variable s. Reply with only the expression.",
        "expected":"s[-3:]",
        "kind":"code_exact",
        "max_tokens":64,
    },
    {
        "id":"python_dict_access",
        "domain":"coding",
        "prompt":"Which is valid Python for reading dictionary d at key k? A) d[k] B) d.k() C) d->k. Reply with only A, B, or C.",
        "expected":"A",
        "kind":"casefold_exact",
        "max_tokens":32,
    },
    {
        "id":"python_output",
        "domain":"coding",
        "prompt":"Python: def f(x): return x*2+1. What does f(4) return? Reply with only the integer.",
        "expected":"9",
        "kind":"exact",
        "max_tokens":48,
    },
)


def _clean(text: str) -> str:
    s=str(text or "").strip()
    fence=chr(96)*3
    if s.startswith(fence):
        first_newline=s.find("\n")
        if first_newline>=0:
            s=s[first_newline+1:]
        else:
            s=s[len(fence):]
    if s.endswith(fence):
        s=s[:-len(fence)]
    return s.strip().strip(chr(96)).strip()


def grade(case: dict[str,Any], answer: str) -> bool:
    got=_clean(answer)
    expected=str(case.get("expected") or "").strip()
    kind=case.get("kind")
    if kind=="code_exact":
        return re.sub(r"\s+","",got)==re.sub(r"\s+","",expected)
    if kind=="casefold_exact":
        return got.casefold()==expected.casefold()
    return got==expected


def _fresh_row_map(models, *, domain="main", min_samples=None, max_age_days=MAX_AGE_DAYS):
    wanted={str(x) for x in models if x}
    now=time.time()
    out={}
    if min_samples is None:
        min_samples=MIN_SAMPLES if domain=="main" else DOMAIN_MIN_SAMPLES.get(domain,1)
    for row in model_arena(domain):
        model=str(row.get("model") or "")
        if model not in wanted:
            continue
        samples=int(row.get("samples") or 0)
        age_days=max(0.0,(now-float(row.get("updated") or 0))/86400)
        if samples < int(min_samples) or age_days > float(max_age_days):
            continue
        out[model]={
            "score":round(float(row.get("score") or 0),2),
            "latency":round(float(row.get("latency") or 0),3),
            "samples":samples,
            "age_days":round(age_days,3),
            "updated":float(row.get("updated") or 0),
        }
    return out


def routing_signal(models) -> dict[str,Any]:
    models=[str(x) for x in models if x]
    scores=_fresh_row_map(models)
    ready=bool(models) and all(m in scores for m in models)
    newest=max((v.get("updated",0) for v in scores.values()),default=0)
    oldest=min((v.get("updated",0) for v in scores.values()),default=0)
    return {
        "version":VERSION,
        "ready":ready,
        "candidate_count":len(models),
        "measured_count":len(scores),
        "scores":scores,
        "newest":newest,
        "oldest":oldest,
    }


def profile_domain(profile: str) -> str:
    p=str(profile or "").strip().lower()
    if p=="coding":
        return "coding"
    if p in {"mathscience","analysis","knowledge","research"}:
        return "reasoning"
    if p=="writing":
        return "instruction"
    return ""


def domain_signal(models, profile: str) -> dict[str,Any]:
    models=[str(x) for x in models if x]
    domain=profile_domain(profile)
    if not domain:
        return {
            "version":VERSION,
            "domain":"",
            "profile":str(profile or ""),
            "ready":False,
            "candidate_count":len(models),
            "measured_count":0,
            "scores":{},
        }
    scores=_fresh_row_map(
        models,
        domain=domain,
        min_samples=DOMAIN_MIN_SAMPLES.get(domain,1),
    )
    ready=bool(models) and all(m in scores for m in models)
    return {
        "version":VERSION,
        "domain":domain,
        "profile":str(profile or ""),
        "ready":ready,
        "candidate_count":len(models),
        "measured_count":len(scores),
        "scores":scores,
        "newest":max((v.get("updated",0) for v in scores.values()),default=0),
        "oldest":min((v.get("updated",0) for v in scores.values()),default=0),
    }


def fresh_score(model: str, domain: str="main") -> dict[str,Any]:
    """Return one complete, fresh objective score window or an empty dict."""
    model=str(model or "")
    if not model:
        return {}
    rows=_fresh_row_map(
        [model],
        domain=domain,
        min_samples=MIN_SAMPLES if domain=="main" else DOMAIN_MIN_SAMPLES.get(domain,1),
    )
    return dict(rows.get(model) or {})


def challenger_signal(model: str, profile: str) -> dict[str,Any]:
    """Conservative proof gate before a non-incumbent can enter main-brain routing.

    A challenger must first complete the entire global arena. For task profiles
    with a domain benchmark it must also be perfect on that complete domain set.
    Profiles without a domain benchmark require at least 7/8 global checks.
    """
    model=str(model or "")
    domain=profile_domain(profile)
    main=fresh_score(model,"main")
    domain_row=fresh_score(model,domain) if domain else {}
    main_score=float(main.get("score") or 0)
    domain_score=float(domain_row.get("score") or 0)
    if not main:
        eligible=False
        reason="missing_complete_global_window"
    elif domain:
        eligible=bool(domain_row and main_score>=62.5 and domain_score>=100.0)
        reason="complete_domain_proof" if eligible else "domain_threshold_not_met"
    else:
        # Do not promote a challenger into casual/creative chat from a tiny
        # objective benchmark that does not measure conversation quality.
        eligible=False
        reason="no_matching_objective_domain"
    return {
        "model":model,
        "profile":str(profile or "chat").lower(),
        "domain":domain,
        "eligible":eligible,
        "reason":reason,
        "main":main,
        "domain_score":domain_row,
        "requirements":{
            "global_samples":MIN_SAMPLES,
            "global_min_score":62.5 if domain else None,
            "domain_samples":DOMAIN_MIN_SAMPLES.get(domain,0) if domain else 0,
            "domain_min_score":100.0 if domain else None,
        },
    }


def _run_one(model: str, ask_fn: Callable[[str,str,int],str]) -> dict[str,Any]:
    rows=[]
    completed=0
    passed=0
    by_domain={}
    for case in CASES:
        started=time.time()
        try:
            answer=ask_fn(model,case["prompt"],int(case.get("max_tokens") or 64))
            latency=max(0.0,time.time()-started)
            ok=grade(case,answer)
            completed+=1
            passed+=int(ok)
            domain=str(case["domain"])
            bucket=by_domain.setdefault(domain,{"completed":0,"passed":0,"latencies":[]})
            bucket["completed"]+=1
            bucket["passed"]+=int(ok)
            bucket["latencies"].append(latency)
            rows.append({
                "id":case["id"],
                "domain":domain,
                "passed":ok,
                "latency":round(latency,3),
                "answer":_clean(answer)[:120],
            })
        except Exception as exc:
            rows.append({
                "id":case["id"],
                "domain":case["domain"],
                "passed":False,
                "transport_error":exc.__class__.__name__,
            })

    score=round(100*passed/max(1,completed),1) if completed else None
    if completed:
        latencies=[float(x.get("latency") or 0) for x in rows if "latency" in x]
        avg_latency=sum(latencies)/max(1,len(latencies))
        set_model_score(model,"main",score,avg_latency,completed)

    domains={}
    for domain,bucket in by_domain.items():
        n=int(bucket["completed"])
        dscore=round(100*int(bucket["passed"])/max(1,n),1)
        dlat=sum(bucket["latencies"])/max(1,len(bucket["latencies"]))
        set_model_score(model,domain,dscore,dlat,n)
        domains[domain]={
            "completed":n,
            "passed":int(bucket["passed"]),
            "score":dscore,
            "latency":round(dlat,3),
        }

    return {
        "model":model,
        "completed":completed,
        "passed":passed,
        "score":score,
        "domains":domains,
        "cases":rows,
    }


def run(models, ask_fn: Callable[[str,str,int],str], *, force=False) -> dict[str,Any]:
    global _LAST_ATTEMPT
    models=list(dict.fromkeys(str(x) for x in models if x))
    if not models:
        return {"ok":False,"version":VERSION,"reason":"no_configured_main_models","results":[],"routing":routing_signal([])}

    current=routing_signal(models)
    now=time.time()
    if not force and current.get("ready") and current.get("oldest") and now-float(current["oldest"]) < RUN_TTL_SECONDS:
        return {"ok":True,"version":VERSION,"skipped":"fresh","results":[],"routing":current}

    if not force and _LAST_ATTEMPT and now-_LAST_ATTEMPT < RETRY_COOLDOWN_SECONDS:
        return {"ok":True,"version":VERSION,"skipped":"cooldown","results":[],"routing":current}

    if not _LOCK.acquire(blocking=False):
        return {"ok":True,"version":VERSION,"skipped":"already_running","results":[],"routing":current}

    _LAST_ATTEMPT=now
    try:
        with ThreadPoolExecutor(max_workers=min(3,len(models))) as ex:
            results=list(ex.map(lambda m:_run_one(m,ask_fn),models))
        signal=routing_signal(models)
        return {
            "ok":True,
            "version":VERSION,
            "models_tested":len(models),
            "cases_per_model":len(CASES),
            "results":results,
            "routing":signal,
        }
    finally:
        _LOCK.release()


def status(models=None) -> dict[str,Any]:
    models=list(models or [])
    signal=routing_signal(models) if models else {
        "ready":False,
        "candidate_count":0,
        "measured_count":0,
        "scores":{},
    }
    return {
        "version":VERSION,
        "objective_cases":len(CASES),
        "min_samples":MIN_SAMPLES,
        "domain_min_samples":DOMAIN_MIN_SAMPLES,
        "max_age_days":MAX_AGE_DAYS,
        "routing":signal,
        "domain_scores":{d:model_arena(d) for d in DOMAIN_MIN_SAMPLES},
        "challenger_gate":{
            "no_domain_promotion":False,
            "global_with_domain_min_score":62.5,
            "domain_min_score":100.0,
            "freshness_days":MAX_AGE_DAYS,
        },
        "all_scores":model_arena("main"),
        "running":_LOCK.locked(),
        "last_attempt":_LAST_ATTEMPT,
    }
