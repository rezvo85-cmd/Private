"""RONN R23 release/evaluation lab.

Every major R23 capability has a deterministic architecture regression. External
provider quality is intentionally not faked in CI; live provider health is measured
separately at runtime.
"""
from __future__ import annotations

import uuid

from r23_brain import plan, resolve_route, status as brain_status
from r23_capabilities import unknown_candidates, retrieval_reason, status as capability_status
from r23_context import compress_history
from r23_agent_runtime import status as agent_status
from r23_research import subqueries
from r16_simulation import project_model
from project_brain import ensure_project, remember, retrieve
from r19_context import record_failure, relevant_failures

MODELS={
    "fast":"openai/gpt-oss-20b",
    "smart":"openai/gpt-oss-120b",
    "creator":"qwen/qwen3.6-27b",
    "vision":"qwen/qwen3.6-27b",
    "live":"groq/compound-mini",
    "research":"groq/compound",
    "nvidia":"nvidia/nemotron-3-super-120b-a12b",
    "or_nemotron":"nvidia/nemotron-3-ultra-550b-a55b:free",
    "or_deepseek":"deepseek/deepseek-v4-flash:free",
    "or_qwen":"qwen/qwen3.8-27b:free",
}
PROVIDERS={"groq":True,"nvidia":True,"openrouter":True}


def _case(name,feature,fn):
    try:
        ok=bool(fn())
        return {"name":name,"feature":feature,"passed":ok,"error":"" if ok else "condition failed"}
    except Exception as exc:
        return {"name":name,"feature":feature,"passed":False,"error":str(exc)[:240]}


def run():
    long_history=[]
    for i in range(24):
        long_history.append({"role":"user","content":f"Project rule {i}: keep the API names stable and remember decision {i}."})
        long_history.append({"role":"assistant","content":"Understood; the project decision is preserved."})

    hard=(
        "Design the entire production architecture for a multi-service platform with multiple files, "
        "dependencies, failure recovery, migration, deployment, observability, security, root cause "
        "analysis, verification, and a complete system plan."
    )
    hard_plan=plan(hard,file_names=["a.py","b.py","c.py","d.py"],has_project=True)
    code_plan=plan("Fix this Python error, run tests, repair it and retest until it works.",
                   file_names=["main.py","helper.py"],has_project=True)
    unknown_plan=plan("what does ZXQ_991 mean")

    owner="r23_eval_"+uuid.uuid4().hex[:10]
    pid=ensure_project("r23-eval-"+owner)
    remember(pid,"decision","api_name","Keep the public API name stable.",.95,"r23_eval")
    fail_id=record_failure(owner,"When a parser test fails, preserve the input contract before changing output.","coding")

    tests=[
        _case("strongest configured model owns normal reasoning","1_stronger_main_brain",
              lambda:resolve_route(plan("Explain why caching helps web applications."),PROVIDERS,MODELS)[0]==MODELS["or_nemotron"]),

        _case("agent runtime exposes browser code and computer adapters","2_full_agent_runtime",
              lambda:(lambda s:s.get("browser") and s.get("controlled_code_execution") and s.get("computer_adapter"))(agent_status())),

        _case("code test fix retest activates for attached repair work","3_code_test_fix_retest",
              lambda:bool(code_plan["capabilities"]["code_fix_loop"] and code_plan["capabilities"]["agent_runtime"])),

        _case("project brain writes and retrieves durable project facts","4_permanent_project_brain",
              lambda:any(x.get("key")=="api_name" for x in retrieve(pid,"API name",10).get("facts",[]))),

        _case("long context compresses old decisions without dumping all turns","5_long_context_compression",
              lambda:(lambda x:x["items"]>0 and x["source_turns"]>20 and len(x["text"])<=11000)(compress_history(long_history))),

        _case("evaluation lab declares all eleven capabilities","6_real_evaluation_lab",
              lambda:capability_status().get("feature_count")==11 and len(capability_status().get("features",{}))==11),

        _case("very hard work activates automatic model competition","7_automatic_model_competition",
              lambda:bool(hard_plan.get("use_council") and hard_plan["capabilities"]["model_competition"])),

        _case("world model maps cross-file dependencies","8_world_model_simulation",
              lambda:any(e.get("to")=="b.py" for e in project_model([
                  {"name":"a.py","content":"import b\nprint(b.x)"},
                  {"name":"b.py","content":"x=1"},
              ]).get("edges",[]))),

        _case("failure learning stores and retrieves relevant lessons","9_failure_learning",
              lambda:bool(fail_id and relevant_failures(owner,"parser input contract coding failure",5))),

        _case("autonomous research generates multiple useful search angles","10_autonomous_research",
              lambda:len(subqueries("Fix package ZXQ_991 error",unknown_terms=["ZXQ_991"],depth="deep"))>=3),

        _case("unknown terms automatically trigger universal retrieval","11_universal_retrieval",
              lambda:bool("ZXQ_991" in unknown_candidates("what does ZXQ_991 mean")
                          and retrieval_reason("what does ZXQ_991 mean")["required"]
                          and unknown_plan["needs_live"]
                          and unknown_plan["capabilities"]["universal_retrieval"])),
    ]

    passed=sum(1 for x in tests if x["passed"])
    return {
        "version":"R23-EVAL-1",
        "passed":passed,
        "total":len(tests),
        "score":round(100*passed/max(1,len(tests)),1),
        "all_11_ready":passed==11 and len(tests)==11,
        "tests":tests,
        "brain":brain_status(),
        "scope":"Architecture/regression coverage for all 11 R23 capabilities; live model quality/provider availability is measured separately.",
    }


if __name__=="__main__":
    print(run())
