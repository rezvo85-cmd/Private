"""RONN R23 release/evaluation lab.

Every major R23 capability has a deterministic architecture regression. External
provider quality is intentionally not faked in CI; live provider health is measured
separately at runtime.
"""
from __future__ import annotations

from r23_brain import plan, resolve_route, status as brain_status, competition_pair
from r23_brain_arena import (
    grade as arena_grade,
    routing_signal as arena_routing_signal,
    domain_signal as arena_domain_signal,
)
from r23_capabilities import unknown_candidates, retrieval_reason, status as capability_status
from r23_knowledge_rescue import gap_signal as knowledge_gap_signal, should_buffer as knowledge_gap_should_buffer
from r23_context import compress_history, project_scope_active, project_scope_key
from r23_agent_runtime import status as agent_status, evidence_contract as agent_evidence_contract
from r23_research import subqueries
from r16_simulation import project_model, simulate as simulate_changes
from project_brain import ensure_project, remember, retrieve, export_project, import_project, set_model_score
from experience_engine import learn_lesson, retrieve_lessons, ingest_portable_outcomes, profile_feedback_signal

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

    correction_history=[
        {"role":"user","content":"Keep the public API timeout at 10 seconds."},
        {"role":"assistant","content":"The timeout is 10 seconds."},
        {"role":"user","content":"Remember build target R23."},
        {"role":"assistant","content":"Build target R23 noted."},
        {"role":"user","content":"Remember build target R23."},
        {"role":"assistant","content":"Still using R23."},
        {"role":"user","content":"Actually, change that: keep the public API timeout at 30 seconds instead."},
        {"role":"assistant","content":"Updated to 30 seconds."},
    ]
    for i in range(10):
        correction_history.append({"role":"user","content":f"Later project note {i}: continue the current implementation."})
        correction_history.append({"role":"assistant","content":"Continuing with the current implementation."})
    correction_digest=compress_history(correction_history,7000,8)

    hard=(
        "Design the entire production architecture for a multi-service platform with multiple files, "
        "dependencies, failure recovery, migration, deployment, observability, security, root cause "
        "analysis, verification, and a complete system plan."
    )
    hard_plan=plan(hard,file_names=["a.py","b.py","c.py","d.py"],has_project=True)
    code_plan=plan("Fix this Python error, run tests, repair it and retest until it works.",
                   file_names=["main.py","helper.py"],has_project=True)
    unknown_plan=plan("what does ZXQ_991 mean")

    pid=ensure_project("r23-eval-project")
    remember(pid,"decision","api_name","Keep the public API name stable.",.95,"r23_eval")
    portable_snapshot=export_project(pid,20,20)
    restored_pid=ensure_project("r23-eval-project-restored")
    portable_restore=import_project(restored_pid,portable_snapshot,"r23_eval_restore")
    learn_lesson("coding","r23_parser_contract","When a parser test fails, preserve the input contract before changing output.",.95)

    arena_models=dict(MODELS)
    arena_models["or_nemotron"]="arena-eval-nemotron"
    arena_models["nvidia"]="arena-eval-nvidia"
    arena_models["smart"]="arena-eval-groq"
    set_model_score(arena_models["or_nemotron"],"main",75,.40,8)
    set_model_score(arena_models["nvidia"],"main",100,.30,8)
    set_model_score(arena_models["smart"],"main",50,.20,8)
    ingest_portable_outcomes({
        "version":"R23-OUTCOME-1",
        "rows":[
            {"model":arena_models["or_nemotron"],"profile":"coding","good":3,"bad":0,"updated":9999999999999},
            {"model":arena_models["nvidia"],"profile":"coding","good":0,"bad":3,"updated":9999999999999},
            {"model":arena_models["smart"],"profile":"coding","good":1,"bad":2,"updated":9999999999999},
            {"model":arena_models["or_nemotron"],"profile":"analysis","good":0,"bad":4,"updated":9999999999999},
            {"model":arena_models["nvidia"],"profile":"analysis","good":0,"bad":4,"updated":9999999999999},
            {"model":arena_models["smart"],"profile":"analysis","good":0,"bad":4,"updated":9999999999999},
            {"model":arena_models["or_nemotron"],"profile":"chat","good":0,"bad":4,"updated":9999999999999},
            {"model":arena_models["nvidia"],"profile":"chat","good":0,"bad":4,"updated":9999999999999},
            {"model":arena_models["smart"],"profile":"chat","good":0,"bad":4,"updated":9999999999999},
        ],
    })
    adaptive_auto=plan("Analyze this production architecture and compare reliability, scaling, cost, and failure modes.")
    adaptive_auto_route=resolve_route(adaptive_auto,PROVIDERS,arena_models)
    adaptive_fast=plan(
        "Analyze this production architecture and compare reliability, scaling, cost, and failure modes.",
        explicit_mode="fast",
    )
    adaptive_fast_route=resolve_route(adaptive_fast,PROVIDERS,arena_models)
    adaptive_verify=plan("Analyze this production architecture, deploy strategy, migration, and failure recovery.")
    adaptive_verify_route=resolve_route(adaptive_verify,PROVIDERS,arena_models)
    adaptive_simple=plan("hi")
    adaptive_simple_route=resolve_route(adaptive_simple,PROVIDERS,arena_models)

    domain_models=dict(MODELS)
    domain_models["or_nemotron"]="domain-eval-nemotron"
    domain_models["nvidia"]="domain-eval-nvidia"
    domain_models["smart"]="domain-eval-groq"
    set_model_score(domain_models["or_nemotron"],"main",75,.40,8)
    set_model_score(domain_models["nvidia"],"main",100,.30,8)
    set_model_score(domain_models["smart"],"main",60,.20,8)
    set_model_score(domain_models["or_nemotron"],"coding",100,.35,3)
    set_model_score(domain_models["nvidia"],"coding",35,.25,3)
    set_model_score(domain_models["smart"],"coding",60,.18,3)
    domain_code_plan=plan("Fix this Python bug in my code.")
    domain_code_route=resolve_route(domain_code_plan,PROVIDERS,domain_models)
    apex_pair=competition_pair(
        arena_models["nvidia"],
        "coding",
        PROVIDERS,
        arena_models,
    )

    evidence_sample=agent_evidence_contract({
        "research":{"sources":[
            {"id":"R1","url":"https://example.com/read","read":True},
            {"id":"R2","url":"https://example.com/snippet","read":False},
        ]},
        "browser_pages":[
            {"url":"https://example.com/page","status":200,"text":"retrieved page"},
            {"url":"https://example.com/bad","status":"unknown","text":"not trustworthy"},
        ],
        "executed":["world_model","code_test_fix_retest"],
        "world_model":{"nodes":2},
        "code_loop":{"ok":True,"verified":False},
        "errors":[],
    })
    verified_evidence_sample=agent_evidence_contract({
        "executed":["code_test_fix_retest"],
        "code_loop":{"ok":True,"verified":True},
    })

    tests=[
        _case("main brain combines objective arena and profile outcomes","1_stronger_main_brain",
              lambda:bool(
                  arena_grade({"kind":"exact","expected":"877"},"877")
                  and arena_routing_signal([
                      arena_models["or_nemotron"],arena_models["nvidia"],arena_models["smart"]
                  ])["ready"]
                  and profile_feedback_signal([
                      arena_models["or_nemotron"],arena_models["nvidia"],arena_models["smart"]
                  ],"coding",3)["ready"]
                  and resolve_route(
                      plan("Explain why caching helps web applications."),PROVIDERS,arena_models
                  )[0]==arena_models["nvidia"]
                  and resolve_route(
                      plan("Fix this Python bug in my code."),PROVIDERS,arena_models
                  )[0]==arena_models["or_nemotron"]
                  and adaptive_auto_route[1]=="deep"
                  and adaptive_auto.get("adaptive_effort",{}).get("applied")
                  and adaptive_auto.get("depth")=="deep"
                  and adaptive_fast_route[1]=="knowledge"
                  and adaptive_fast.get("depth")=="fast"
                  and adaptive_fast.get("adaptive_effort",{}).get("reason")=="explicit_mode_preserved"
                  and adaptive_fast.get("second_pass") is False
                  and adaptive_verify_route[1]=="deep"
                  and adaptive_verify.get("verify") is True
                  and adaptive_verify.get("second_pass") is True
                  and adaptive_verify.get("adaptive_effort",{}).get("second_pass") is True
                  and adaptive_verify.get("adaptive_effort",{}).get("correction_pass_added") is True
                  and adaptive_verify.get("prompt_policy",{}).get("include_verification_directive") is True
                  and adaptive_simple.get("depth")=="fast"
                  and adaptive_simple.get("second_pass") is False
                  and adaptive_simple.get("adaptive_effort",{}).get("applied") is False
                  and arena_domain_signal([
                      domain_models["or_nemotron"],domain_models["nvidia"],domain_models["smart"]
                  ],"coding")["ready"]
                  and domain_code_route[0]==domain_models["or_nemotron"]
                  and domain_code_plan.get("main_brain_domain_arena",{}).get("domain")=="coding"
              )),

        _case("agent runtime exposes browser code and computer adapters","2_full_agent_runtime",
              lambda:(lambda s:s.get("browser") and s.get("controlled_code_execution") and s.get("computer_adapter"))(agent_status())),

        _case("code test fix retest activates for attached repair work","3_code_test_fix_retest",
              lambda:bool(code_plan["capabilities"]["code_fix_loop"] and code_plan["capabilities"]["agent_runtime"])),

        _case("project brain scopes and retrieves durable project facts","4_permanent_project_brain",
              lambda:bool(
                  project_scope_active("core-project-123","")
                  and project_scope_key("core-project-123","").startswith("core:")
                  and plan("Continue this project.",has_project=True)["capabilities"]["project_brain"]
                  and any(x.get("key")=="api_name" for x in retrieve(pid,"API name",10).get("facts",[]))
                  and portable_restore.get("ok")
                  and any(x.get("key")=="api_name" for x in retrieve(restored_pid,"API name",10).get("facts",[]))
              )),

        _case("long context keeps newest state, corrections, and compact history","5_long_context_compression",
              lambda:bool(
                  (lambda x:x["items"]>0 and x["source_turns"]>20 and len(x["text"])<=11000)(compress_history(long_history))
                  and "Latest corrections / superseding instructions" in correction_digest.get("text","")
                  and "30 seconds instead" in correction_digest.get("text","")
                  and "Precedence: newest explicit user instruction wins" in correction_digest.get("text","")
                  and "[turn " in correction_digest.get("text","")
                  and correction_digest.get("superseded_duplicates",0)>=1
                  and correction_digest.get("superseded_conflicts",0)>=1
                  and correction_digest.get("text","").count("Remember build target R23.")==1
                  and "10 seconds" not in correction_digest.get("text","")
              )),

        _case("evaluation lab declares all eleven capabilities","6_real_evaluation_lab",
              lambda:capability_status().get("feature_count")==11 and len(capability_status().get("features",{}))==11),

        _case("very hard work uses R23-primary-owned diverse model competition","7_automatic_model_competition",
              lambda:bool(
                  hard_plan.get("use_council")
                  and hard_plan["capabilities"]["model_competition"]
                  and apex_pair.get("primary_preserved")
                  and apex_pair.get("diverse")
                  and apex_pair.get("models",[])[0]==arena_models["nvidia"]
                  and len(apex_pair.get("models",[]))==2
                  and apex_pair.get("models",[])[1]!=arena_models["nvidia"]
              )),

        _case("world model maps dependencies and simulates change impact","8_world_model_simulation",
              lambda:bool(
                  any(e.get("to")=="b.py" for e in project_model([
                      {"name":"a.py","content":"import b\nprint(b.x)"},
                      {"name":"b.py","content":"x=1"},
                  ]).get("edges",[]))
                  and (lambda sim: sim.get("risk_score",0)>0 and bool(sim.get("changes")))(
                      simulate_changes(
                          [
                              {"name":"a.py","content":"import b\nprint(b.x)"},
                              {"name":"b.py","content":"x=1"},
                          ],
                          [
                              {"name":"a.py","content":"import b\nprint(b.x)"},
                              {"name":"b.py","content":"x=2"},
                          ],
                      )
                  )
              )),

        _case("failure learning stores and retrieves relevant lessons","9_failure_learning",
              lambda:any("preserve the input contract" in str(x.get("lesson","")).lower()
                         for x in retrieve_lessons("coding",20))),

        _case("autonomous research and evidence states stay evidence-bound","10_autonomous_research",
              lambda:bool(
                  len(subqueries("Fix package ZXQ_991 error",unknown_terms=["ZXQ_991"],depth="deep"))>=3
                  and evidence_sample["retrieval"]["read_page_count"]==1
                  and evidence_sample["retrieval"]["snippet_only_count"]==1
                  and evidence_sample["retrieval"]["explicit_browser_pages_read"]==1
                  and evidence_sample["computed_static_analysis"] is True
                  and evidence_sample["runtime_execution"]["attempted"] is True
                  and evidence_sample["runtime_execution"]["reported_ok"] is True
                  and evidence_sample["runtime_execution"]["verified_success"] is False
                  and verified_evidence_sample["runtime_execution"]["verified_success"] is True
              )),

        _case("unknown terms and admitted knowledge gaps trigger retrieval rescue","11_universal_retrieval",
              lambda:bool("ZXQ_991" in unknown_candidates("what does ZXQ_991 mean")
                          and retrieval_reason("what does ZXQ_991 mean")["required"]
                          and unknown_plan["needs_live"]
                          and unknown_plan["capabilities"]["universal_retrieval"]
                          and knowledge_gap_should_buffer("What is VexaRuntime?","knowledge")
                          and knowledge_gap_signal(
                              "I'm not familiar with VexaRuntime, so I can't identify it reliably.",
                              "What is VexaRuntime?",
                              "knowledge",
                          )["required"]
                          and not knowledge_gap_signal(
                              "I'm not sure which color you would prefer.",
                              "Which color should I use for this fictional logo?",
                              "creative",
                          )["required"])),
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
