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

from project_brain import model_arena, score_model

VERSION="R23-BRAIN-ARENA-1"
MIN_SAMPLES=4
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
    return got==expected


def _fresh_row_map(models, *, min_samples=MIN_SAMPLES, max_age_days=MAX_AGE_DAYS):
    wanted={str(x) for x in models if x}
    now=time.time()
    out={}
    for row in model_arena("main"):
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


def _run_one(model: str, ask_fn: Callable[[str,str,int],str]) -> dict[str,Any]:
    rows=[]
    completed=0
    passed=0
    for case in CASES:
        started=time.time()
        try:
            answer=ask_fn(model,case["prompt"],int(case.get("max_tokens") or 64))
            latency=max(0.0,time.time()-started)
            ok=grade(case,answer)
            numeric=100.0 if ok else 0.0
            score_model(model,"main",numeric,latency)
            score_model(model,str(case["domain"]),numeric,latency)
            completed+=1
            passed+=int(ok)
            rows.append({
                "id":case["id"],
                "domain":case["domain"],
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
    return {
        "model":model,
        "completed":completed,
        "passed":passed,
        "score":round(100*passed/max(1,completed),1) if completed else None,
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
        "max_age_days":MAX_AGE_DAYS,
        "routing":signal,
        "all_scores":model_arena("main"),
        "running":_LOCK.locked(),
        "last_attempt":_LAST_ATTEMPT,
    }
