"""RONN R23 Progressive Quality Lab.

A larger objective live-model benchmark that is intentionally manual/on-demand.
CI tests the lab architecture without calling providers. Live scores influence
main-brain routing only when every compared candidate has the same complete,
fresh benchmark tier.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from project_brain import model_arena, set_model_score

VERSION="R23-QUALITY-LAB-1"
MAX_AGE_DAYS=30
RETRY_COOLDOWN_SECONDS=60*60
TIER_STAGE={"screen":1,"standard":2,"deep":3}
TIER_ORDER=("deep","standard","screen")

_LOCK=threading.Lock()
_LAST_ATTEMPT=0.0

# Two cases per category at each stage => 12 / 24 / 36 cumulative cases.
CASES=(
    # Stage 1 — cheap screen.
    {"id":"s1_instruction_reverse","stage":1,"category":"instruction",
     "prompt":"Take the words north east west. Reverse their order, convert to uppercase, and join with >. Reply only with the result.",
     "expected":"WEST>EAST>NORTH","kind":"exact","max_tokens":48},
    {"id":"s1_instruction_sort","stage":1,"category":"instruction",
     "prompt":"amber=6, cobalt=2, jade=4. Sort the labels by numeric value ascending and reply only as comma-separated lowercase labels.",
     "expected":"cobalt,jade,amber","kind":"casefold_exact","max_tokens":48},
    {"id":"s1_reasoning_arithmetic","stage":1,"category":"reasoning",
     "prompt":"Compute (18 * 7) + 15. Reply only with the integer.",
     "expected":"141","kind":"exact","max_tokens":48},
    {"id":"s1_reasoning_logic","stage":1,"category":"reasoning",
     "prompt":"Every L is a Q. No Q is an R. Can any L be an R? Reply only YES or NO.",
     "expected":"NO","kind":"casefold_exact","max_tokens":48},
    {"id":"s1_coding_python_range","stage":1,"category":"coding",
     "prompt":"Python: what does list(range(2,8,2)) contain? Reply only as comma-separated integers with no brackets.",
     "expected":"2,4,6","kind":"code_exact","max_tokens":64},
    {"id":"s1_coding_js_map","stage":1,"category":"coding",
     "prompt":"JavaScript: what string is produced by [1,2,3].map(n=>n*2).join('-')? Reply only with the string.",
     "expected":"2-4-6","kind":"exact","max_tokens":64},
    {"id":"s1_evidence_read_page","stage":1,"category":"evidence",
     "prompt":"Evidence state: READ PAGE from the official documentation says 'Version 2 supports feature X.' Claim: Version 2 supports feature X. Reply only SUPPORTED or UNSUPPORTED.",
     "expected":"SUPPORTED","kind":"casefold_exact","max_tokens":48},
    {"id":"s1_evidence_snippet","stage":1,"category":"evidence",
     "prompt":"Evidence state: SEARCH SNIPPET ONLY says a product launched May 3; the page itself was not read. Is the exact May 3 launch date verified from the page? Reply only YES or NO.",
     "expected":"NO","kind":"casefold_exact","max_tokens":48},
    {"id":"s1_context_timeout","stage":1,"category":"context",
     "prompt":"Earlier requirement: timeout=10 seconds. Newer correction: actually use timeout=30 seconds instead. What is the current timeout? Reply only with the integer.",
     "expected":"30","kind":"exact","max_tokens":48},
    {"id":"s1_context_rename","stage":1,"category":"context",
     "prompt":"Older project name: NOVA. Newer explicit instruction: rename the project to RONN going forward. Reply only with the current project name.",
     "expected":"RONN","kind":"casefold_exact","max_tokens":48},
    {"id":"s1_tools_none","stage":1,"category":"tools",
     "prompt":"Choose the best action for this task: 'Write a friendly one-sentence greeting.' Options: NONE, LIVE_RESEARCH, CODE_EXECUTE, WORLD_MODEL, BROWSER_URL, COMPUTER_OBSERVE. Reply only with one option.",
     "expected":"NONE","kind":"casefold_exact","max_tokens":48},
    {"id":"s1_tools_live","stage":1,"category":"tools",
     "prompt":"Choose the best action for this task: 'What is today's USD to EUR exchange rate?' Options: NONE, LIVE_RESEARCH, CODE_EXECUTE, WORLD_MODEL, BROWSER_URL, COMPUTER_OBSERVE. Reply only with one option.",
     "expected":"LIVE_RESEARCH","kind":"casefold_exact","max_tokens":48},

    # Stage 2 — broader standard proof.
    {"id":"s2_instruction_filter","stage":2,"category":"instruction",
     "prompt":"Start with red blue green. Remove blue, uppercase the remaining words, and join them with +. Reply only with the result.",
     "expected":"RED+GREEN","kind":"exact","max_tokens":48},
    {"id":"s2_instruction_ids","stage":2,"category":"instruction",
     "prompt":"IDs are B3 A1 C2. Sort by the numeric suffix ascending, then output only the letters with no separators.",
     "expected":"ACB","kind":"exact","max_tokens":48},
    {"id":"s2_reasoning_probability","stage":2,"category":"reasoning",
     "prompt":"Two fair coins are flipped. What is the probability of getting exactly one head? Reply only as a simplified fraction.",
     "expected":"1/2","kind":"exact","max_tokens":64},
    {"id":"s2_reasoning_algebra","stage":2,"category":"reasoning",
     "prompt":"Solve 3x + 7 = 31. Reply only with the value of x.",
     "expected":"8","kind":"exact","max_tokens":64},
    {"id":"s2_coding_alias","stage":2,"category":"coding",
     "prompt":"Python: a=[1,2]; b=a; b.append(3). What is len(a)? Reply only with the integer.",
     "expected":"3","kind":"exact","max_tokens":64},
    {"id":"s2_coding_comprehension","stage":2,"category":"coding",
     "prompt":"Python: what is [x*x for x in range(4) if x%2]? Reply only as comma-separated integers with no brackets.",
     "expected":"1,9","kind":"code_exact","max_tokens":64},
    {"id":"s2_evidence_runtime","stage":2,"category":"evidence",
     "prompt":"Evidence: static analysis predicts success. A controlled runtime execution then exits 0 and all tests pass. Is successful execution runtime-verified? Reply only VERIFIED or NOT_VERIFIED.",
     "expected":"VERIFIED","kind":"casefold_exact","max_tokens":48},
    {"id":"s2_evidence_inference","stage":2,"category":"evidence",
     "prompt":"A claim is based only on a model inference. No page, tool result, measurement, or runtime observation supports it. Is the claim evidence-supported? Reply only YES or NO.",
     "expected":"NO","kind":"casefold_exact","max_tokens":48},
    {"id":"s2_context_users","stage":2,"category":"context",
     "prompt":"Old requirement: max users=100. Later: change it to 250. Latest explicit correction: ignore 250 and use 200. Reply only with the current max users integer.",
     "expected":"200","kind":"exact","max_tokens":48},
    {"id":"s2_context_auth","stage":2,"category":"context",
     "prompt":"Initial design used PASSWORD auth. A later decision replaced it with OAUTH. Latest note says keep the OAUTH decision. Reply only with the current auth method.",
     "expected":"OAUTH","kind":"casefold_exact","max_tokens":48},
    {"id":"s2_tools_world","stage":2,"category":"tools",
     "prompt":"Choose the best action: 'Before changing this attached multi-file service, map dependencies and what could break.' Options: NONE, LIVE_RESEARCH, CODE_EXECUTE, WORLD_MODEL, BROWSER_URL, COMPUTER_OBSERVE. Reply only with one option.",
     "expected":"WORLD_MODEL","kind":"casefold_exact","max_tokens":48},
    {"id":"s2_tools_code","stage":2,"category":"tools",
     "prompt":"Choose the best action: 'An attached Python program fails intermittently; run it to reproduce the failure before claiming a fix.' Options: NONE, LIVE_RESEARCH, CODE_EXECUTE, WORLD_MODEL, BROWSER_URL, COMPUTER_OBSERVE. Reply only with one option.",
     "expected":"CODE_EXECUTE","kind":"casefold_exact","max_tokens":48},

    # Stage 3 — harder deep proof.
    {"id":"s3_instruction_mapping","stage":3,"category":"instruction",
     "prompt":"kiwi=3, plum=8, pear=5. Sort labels by value descending, take the first letter of each sorted label, uppercase them, and concatenate with no separators. Reply only with the result.",
     "expected":"PPK","kind":"exact","max_tokens":64},
    {"id":"s3_instruction_length_sort","stage":3,"category":"instruction",
     "prompt":"Words: delta alpha echo beta. Sort by length ascending; break equal-length ties alphabetically. Join with /. Reply only with the result.",
     "expected":"beta/echo/alpha/delta","kind":"casefold_exact","max_tokens":64},
    {"id":"s3_reasoning_arrangements","stage":3,"category":"reasoning",
     "prompt":"How many distinct arrangements are there of the letters BANANA? Reply only with the integer.",
     "expected":"60","kind":"exact","max_tokens":64},
    {"id":"s3_reasoning_conditional","stage":3,"category":"reasoning",
     "prompt":"Two fair six-sided dice are rolled. Given that their sum is 9, what is the probability the first die is 4? Reply only as a simplified fraction.",
     "expected":"1/4","kind":"exact","max_tokens":64},
    {"id":"s3_coding_bound_default","stage":3,"category":"coding",
     "prompt":"Python: fs=[lambda x=i: x for i in range(3)]. What is [f() for f in fs]? Reply only as comma-separated integers with no brackets.",
     "expected":"0,1,2","kind":"code_exact","max_tokens":72},
    {"id":"s3_coding_shallow_copy","stage":3,"category":"coding",
     "prompt":"Python: d={'a':[1]}; e=d.copy(); e['a'].append(2). What is len(d['a'])? Reply only with the integer.",
     "expected":"2","kind":"exact","max_tokens":72},
    {"id":"s3_evidence_version_conflict","stage":3,"category":"evidence",
     "prompt":"READ PAGE A is current Version 4 documentation and says feature X was removed. READ PAGE B is older Version 3 documentation and says X was supported. Does current Version 4 support X? Reply only YES or NO.",
     "expected":"NO","kind":"casefold_exact","max_tokens":64},
    {"id":"s3_evidence_failed_run","stage":3,"category":"evidence",
     "prompt":"A controlled code run still fails its tests. A model explanation says the bug should now be fixed, but no later successful run exists. Can the fix be called runtime-verified? Reply only YES or NO.",
     "expected":"NO","kind":"casefold_exact","max_tokens":64},
    {"id":"s3_context_database","stage":3,"category":"context",
     "prompt":"Decision history: use POSTGRES. Later correction: switch to MYSQL. Latest explicit correction: switch back to POSTGRES and treat that as current. Reply only with the current database.",
     "expected":"POSTGRES","kind":"casefold_exact","max_tokens":48},
    {"id":"s3_context_region","stage":3,"category":"context",
     "prompt":"Old production region: WEST. Later note: move to EAST. Latest clarification: EAST is staging only; production stays WEST. Reply only with the current production region.",
     "expected":"WEST","kind":"casefold_exact","max_tokens":48},
    {"id":"s3_tools_url","stage":3,"category":"tools",
     "prompt":"Choose the best action: 'Read the explicit URL I supplied and summarize a section from that page.' Options: NONE, LIVE_RESEARCH, CODE_EXECUTE, WORLD_MODEL, BROWSER_URL, COMPUTER_OBSERVE. Reply only with one option.",
     "expected":"BROWSER_URL","kind":"casefold_exact","max_tokens":48},
    {"id":"s3_tools_computer","stage":3,"category":"tools",
     "prompt":"Choose the best action: 'Inspect what is currently visible on my connected computer screen before answering.' Options: NONE, LIVE_RESEARCH, CODE_EXECUTE, WORLD_MODEL, BROWSER_URL, COMPUTER_OBSERVE. Reply only with one option.",
     "expected":"COMPUTER_OBSERVE","kind":"casefold_exact","max_tokens":48},
)


def _clean(text: str) -> str:
    s=str(text or "").strip()
    fence=chr(96)*3
    if s.startswith(fence):
        i=s.find("\n")
        s=s[i+1:] if i>=0 else s[len(fence):]
    if s.endswith(fence):
        s=s[:-len(fence)]
    return s.strip().strip(chr(96)).strip()


def grade(case: dict[str,Any], answer: str) -> bool:
    got=_clean(answer)
    expected=str(case.get("expected") or "").strip()
    kind=str(case.get("kind") or "exact")
    if kind=="code_exact":
        return re.sub(r"\s+","",got)==re.sub(r"\s+","",expected)
    if kind=="casefold_exact":
        return got.casefold()==expected.casefold()
    return got==expected


def cases_for_tier(tier: str="screen") -> tuple[dict[str,Any],...]:
    tier=str(tier or "screen").strip().lower()
    if tier not in TIER_STAGE:
        raise ValueError("tier must be screen, standard, or deep")
    stage=TIER_STAGE[tier]
    return tuple(x for x in CASES if int(x["stage"])<=stage)


def tier_case_count(tier: str) -> int:
    return len(cases_for_tier(tier))


def _fresh_rows(models, tier: str, max_age_days: int=MAX_AGE_DAYS) -> dict[str,dict[str,Any]]:
    wanted={str(x) for x in models if x}
    domain="quality_"+str(tier)
    needed=tier_case_count(tier)
    cutoff=time.time()-max(1,int(max_age_days))*86400
    out={}
    for row in model_arena(domain):
        model=str(row.get("model") or "")
        if model not in wanted:
            continue
        if int(row.get("samples") or 0)<needed or float(row.get("updated") or 0)<cutoff:
            continue
        out[model]={
            "score":round(float(row.get("score") or 0),2),
            "latency":round(float(row.get("latency") or 0),3),
            "samples":int(row.get("samples") or 0),
            "updated":float(row.get("updated") or 0),
        }
    return out


def quality_signal(models, tier: str="auto") -> dict[str,Any]:
    models=list(dict.fromkeys(str(x) for x in models if x))
    requested=str(tier or "auto").lower()
    tiers=TIER_ORDER if requested=="auto" else (requested,)
    if requested!="auto" and requested not in TIER_STAGE:
        raise ValueError("tier must be auto, screen, standard, or deep")
    for candidate_tier in tiers:
        scores=_fresh_rows(models,candidate_tier)
        if models and all(m in scores for m in models):
            return {
                "version":VERSION,
                "ready":True,
                "tier":candidate_tier,
                "case_count":tier_case_count(candidate_tier),
                "candidate_count":len(models),
                "measured_count":len(scores),
                "scores":scores,
            }
    return {
        "version":VERSION,
        "ready":False,
        "tier":requested if requested!="auto" else "",
        "candidate_count":len(models),
        "measured_count":0,
        "scores":{},
        "available":{
            t:_fresh_rows(models,t) for t in ("screen","standard","deep")
        },
    }


def _run_model(model: str, ask_fn: Callable[[str,str,int],str], tier: str) -> dict[str,Any]:
    cases=cases_for_tier(tier)
    rows=[]
    for case in cases:
        started=time.time()
        try:
            answer=ask_fn(model,case["prompt"],int(case.get("max_tokens") or 64))
            latency=max(0.0,time.time()-started)
            rows.append({
                "id":case["id"],
                "stage":case["stage"],
                "category":case["category"],
                "passed":grade(case,answer),
                "latency":round(latency,3),
                "answer":_clean(answer)[:120],
            })
        except Exception as exc:
            rows.append({
                "id":case["id"],
                "stage":case["stage"],
                "category":case["category"],
                "passed":False,
                "transport_error":exc.__class__.__name__,
            })

    completed=sum(1 for x in rows if "transport_error" not in x)
    passed=sum(1 for x in rows if x.get("passed") and "transport_error" not in x)
    complete=completed==len(cases)
    score=round(100*passed/max(1,completed),1) if completed else None

    # A deeper run includes every earlier tier, so persist all complete cumulative
    # windows that can be derived from the same provider calls.
    persisted=[]
    requested_stage=TIER_STAGE[tier]
    for name,stage in TIER_STAGE.items():
        if stage>requested_stage:
            continue
        tier_rows=[x for x in rows if int(x.get("stage") or 0)<=stage]
        needed=tier_case_count(name)
        tier_complete=len(tier_rows)==needed and all("transport_error" not in x for x in tier_rows)
        if not tier_complete:
            continue
        tier_passed=sum(1 for x in tier_rows if x.get("passed"))
        tier_score=round(100*tier_passed/needed,1)
        lat=sum(float(x.get("latency") or 0) for x in tier_rows)/needed
        set_model_score(model,"quality_"+name,tier_score,lat,needed)
        persisted.append({"tier":name,"score":tier_score,"samples":needed,"latency":round(lat,3)})

    categories={}
    for category in sorted({x["category"] for x in cases}):
        subset=[x for x in rows if x.get("category")==category]
        done=sum(1 for x in subset if "transport_error" not in x)
        categories[category]={
            "completed":done,
            "passed":sum(1 for x in subset if x.get("passed") and "transport_error" not in x),
            "total":len(subset),
        }
        categories[category]["score"]=round(100*categories[category]["passed"]/max(1,done),1) if done else None

    return {
        "model":model,
        "tier":tier,
        "complete":complete,
        "completed":completed,
        "total":len(cases),
        "passed":passed,
        "score":score,
        "persisted":persisted,
        "categories":categories,
        "cases":rows,
    }


def run(models, ask_fn: Callable[[str,str,int],str], *, tier="screen", force=False) -> dict[str,Any]:
    global _LAST_ATTEMPT
    models=list(dict.fromkeys(str(x) for x in models if x))
    tier=str(tier or "screen").strip().lower()
    if tier not in TIER_STAGE:
        return {"ok":False,"version":VERSION,"reason":"invalid_tier","allowed":list(TIER_STAGE)}
    if not models:
        return {"ok":False,"version":VERSION,"reason":"no_models","results":[]}

    current=quality_signal(models,tier)
    now=time.time()
    if not force and current.get("ready"):
        return {"ok":True,"version":VERSION,"skipped":"fresh","tier":tier,"results":[],"signal":current}
    if not force and _LAST_ATTEMPT and now-_LAST_ATTEMPT<RETRY_COOLDOWN_SECONDS:
        return {"ok":True,"version":VERSION,"skipped":"cooldown","tier":tier,"results":[],"signal":current}
    if not _LOCK.acquire(blocking=False):
        return {"ok":True,"version":VERSION,"skipped":"already_running","tier":tier,"results":[],"signal":current}

    _LAST_ATTEMPT=now
    try:
        with ThreadPoolExecutor(max_workers=min(2,len(models))) as ex:
            results=list(ex.map(lambda m:_run_model(m,ask_fn,tier),models))
        return {
            "ok":True,
            "version":VERSION,
            "tier":tier,
            "models_tested":len(models),
            "cases_per_model":tier_case_count(tier),
            "provider_calls":len(models)*tier_case_count(tier),
            "results":results,
            "signal":quality_signal(models,tier),
            "best_shared_signal":quality_signal(models,"auto"),
        }
    finally:
        _LOCK.release()


def status(models=None) -> dict[str,Any]:
    models=list(models or [])
    categories=sorted({str(x["category"]) for x in CASES})
    return {
        "version":VERSION,
        "manual_only":True,
        "auto_run":False,
        "case_count":len(CASES),
        "categories":categories,
        "category_count":len(categories),
        "tiers":{t:tier_case_count(t) for t in ("screen","standard","deep")},
        "max_age_days":MAX_AGE_DAYS,
        "running":_LOCK.locked(),
        "last_attempt":_LAST_ATTEMPT,
        "signal":quality_signal(models,"auto") if models else {"ready":False,"scores":{}},
        "scores":{
            t:model_arena("quality_"+t) for t in ("screen","standard","deep")
        },
        "routing_rule":"Used only when every compared candidate has the same complete fresh tier.",
    }
