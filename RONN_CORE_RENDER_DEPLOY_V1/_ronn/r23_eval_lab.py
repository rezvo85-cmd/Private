"""RONN R23 release/evaluation lab.

Every major R23 capability has a deterministic architecture regression. External
provider quality is intentionally not faked in CI; live provider health is measured
separately at runtime.
"""
from __future__ import annotations

from r23_brain import (
    plan, resolve_route, status as brain_status, directive as brain_directive, competition_pair,
    reasoning_effort_for_depth, reasoning_effort_for_route,
    reasoning_completion_budget, reasoning_contract,
)
from r23_brain_arena import (
    grade as arena_grade,
    routing_signal as arena_routing_signal,
    domain_signal as arena_domain_signal,
    challenger_signal as arena_challenger_signal,
    shadow_signal as arena_shadow_signal,
    record_shadow_result as arena_record_shadow_result,
)
from r23_capabilities import unknown_candidates, retrieval_reason, status as capability_status
from r23_knowledge_rescue import gap_signal as knowledge_gap_signal, should_buffer as knowledge_gap_should_buffer
from r23_context import compress_history, project_scope_active, project_scope_key, prompt_context_policy
from r23_agent_runtime import (
    status as agent_status,
    evidence_contract as agent_evidence_contract,
    evidence_sufficiency as agent_evidence_sufficiency,
)
from r23_tool_arbiter import (
    should_arbitrate as tool_should_arbitrate,
    parse_verdict as tool_parse_verdict,
    apply_verdict as tool_apply_verdict,
    status as tool_arbiter_status,
)
from r23_research import subqueries
from r23_quality_lab import (
    CASES as QUALITY_CASES,
    cases_for_tier as quality_cases_for_tier,
    grade as quality_grade,
    run as quality_run,
    quality_signal,
    status as quality_status,
)
from r23_confidence import apply_confidence_governor, status as confidence_status
from r23_task_graph import (
    build_task_graph as task_graph_build,
    reconcile_task_graph as task_graph_reconcile,
    recovery_decision as task_graph_recovery_decision,
    mark_recovery_attempted as task_graph_mark_recovery,
    status as task_graph_status,
)
from r16_simulation import project_model, simulate as simulate_changes
from project_brain import (
    ensure_project, remember, retrieve, export_project, import_project, set_model_score,
    export_model_scores, import_model_scores,
)
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

    arbiter_simple=plan("hi")
    arbiter_weather=plan("What's the weather today?")
    arbiter_url=plan("Read https://example.com/docs and explain the API.")
    arbiter_ambiguous=plan(
        "Please inspect why this Python service behaves inconsistently under retries.",
        file_names=["service.py"],
        has_project=True,
    )
    arbiter_high=tool_parse_verdict(
        '{"action":"code_execute","confidence":0.91,"reason":"runtime behavior must be observed"}'
    )
    arbiter_applied=tool_apply_verdict(arbiter_ambiguous,arbiter_high,has_files=True)
    arbiter_low=tool_parse_verdict(
        '{"action":"live_research","confidence":0.55,"reason":"freshness might matter"}'
    )
    arbiter_low_applied=tool_apply_verdict(arbiter_ambiguous,arbiter_low,has_files=True)

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

    challenger_models=dict(MODELS)
    challenger_models["or_nemotron"]="challenger-eval-incumbent"
    challenger_models["nvidia"]="challenger-eval-nvidia"
    challenger_models["smart"]="challenger-eval-groq"
    challenger_models["or_deepseek"]="challenger-eval-deepseek"
    challenger_models["or_qwen"]="challenger-eval-qwen"
    for _m in (
        challenger_models["or_nemotron"],
        challenger_models["nvidia"],
        challenger_models["smart"],
    ):
        set_model_score(_m,"main",100,.30,8)
        set_model_score(_m,"coding",66.67,.25,3)
    set_model_score(challenger_models["or_deepseek"],"main",87.5,.32,8)
    set_model_score(challenger_models["or_deepseek"],"coding",100,.27,3)
    set_model_score(challenger_models["or_deepseek"],"certification",83.3,.31,6)
    arena_record_shadow_result(challenger_models["or_deepseek"],"coding","B")
    arena_record_shadow_result(challenger_models["or_deepseek"],"coding","B")
    arena_record_shadow_result(challenger_models["or_deepseek"],"coding","A")
    set_model_score(challenger_models["or_qwen"],"main",100,.22,8)
    set_model_score(challenger_models["or_qwen"],"coding",100,.18,3)
    set_model_score(challenger_models["or_qwen"],"certification",100,.20,6)
    challenger_plan=plan("Fix this Python bug in my code.")
    challenger_route=resolve_route(challenger_plan,PROVIDERS,challenger_models)
    challenger_pair=competition_pair(
        challenger_models["nvidia"],
        "coding",
        PROVIDERS,
        challenger_models,
    )

    apex_pair=competition_pair(
        arena_models["nvidia"],
        "coding",
        PROVIDERS,
        arena_models,
    )

    quality_models=dict(MODELS)
    quality_models["or_nemotron"]="quality-eval-nemotron"
    quality_models["nvidia"]="quality-eval-nvidia"
    quality_models["smart"]="quality-eval-groq"
    for _m in (
        quality_models["or_nemotron"],
        quality_models["nvidia"],
        quality_models["smart"],
    ):
        set_model_score(_m,"main",100,.20,8)
    set_model_score(quality_models["or_nemotron"],"quality_screen",75,.30,12)
    set_model_score(quality_models["nvidia"],"quality_screen",100,.32,12)
    set_model_score(quality_models["smart"],"quality_screen",83.3,.18,12)
    # A partial higher tier must not override the complete shared screen tier.
    set_model_score(quality_models["nvidia"],"quality_standard",100,.35,24)
    quality_shared_signal=quality_signal([
        quality_models["or_nemotron"],quality_models["nvidia"],quality_models["smart"]
    ],"auto")
    quality_route=resolve_route(
        plan("Explain why caching can improve a web application's performance."),
        PROVIDERS,
        quality_models,
    )

    _quality_answers={x["prompt"]:x["expected"] for x in QUALITY_CASES}
    quality_runner_result=quality_run(
        ["quality-eval-runner"],
        lambda _model,prompt,_max_tokens:_quality_answers[prompt],
        tier="deep",
        force=True,
    )

    confidence_low={
        "explicit_mode":"auto","difficulty":6,"depth":"smart","verify":False,
        "use_council":False,"second_pass":False,"needs_live":False,
        "specialist":"","prompt_policy":{},"profile":"analysis",
    }
    confidence_low_result=apply_confidence_governor(
        confidence_low,"confidence-model",0,{
            "arena":{"ready":False,"scores":{}},
            "domain_arena":{"ready":False,"scores":{}},
            "outcomes":{"ready":False,"scores":{}},
            "quality_lab":{"ready":False,"scores":{}},
        },
    )
    confidence_fast={
        "explicit_mode":"fast","difficulty":6,"depth":"fast","verify":False,
        "use_council":False,"second_pass":False,"needs_live":False,
        "specialist":"","prompt_policy":{},"profile":"analysis",
    }
    confidence_fast_result=apply_confidence_governor(
        confidence_fast,"confidence-model",0,{
            "arena":{"ready":False,"scores":{}},
            "domain_arena":{"ready":False,"scores":{}},
            "outcomes":{"ready":False,"scores":{}},
            "quality_lab":{"ready":False,"scores":{}},
        },
    )
    confidence_high={
        "explicit_mode":"auto","difficulty":3,"depth":"smart","verify":False,
        "use_council":False,"second_pass":False,"needs_live":False,
        "specialist":"","prompt_policy":{},"profile":"analysis",
    }
    confidence_high_result=apply_confidence_governor(
        confidence_high,"confidence-model",0,{
            "arena":{"ready":True,"scores":{
                "confidence-model":{"score":100},"confidence-backup":{"score":60},
            }},
            "domain_arena":{"ready":True,"scores":{
                "confidence-model":{"score":100},"confidence-backup":{"score":40},
            }},
            "outcomes":{"ready":True,"scores":{
                "confidence-model":{"avg_rating":1.0,"ratings":3},
                "confidence-backup":{"avg_rating":0.0,"ratings":3},
            }},
            "quality_lab":{"ready":True,"scores":{
                "confidence-model":{"score":100},"confidence-backup":{"score":75},
            }},
        },
    )

    requirement_plan=plan(
        hard
        + " Keep the public endpoint /v1/chat stable."
        + " Do not rename public fields."
        + " Use exactly 3 validation stages."
        + " Only return JSON from the parser.",
        has_project=True,
    )
    requirement_contract=requirement_plan.get("requirement_contract") or {}
    requirement_prompt=brain_directive(requirement_plan)

    task_graph_simple=plan("hi").get("task_graph") or {}
    task_graph_hard=hard_plan.get("task_graph") or {}

    task_graph_research_decision={
        "difficulty":5,
        "profile":"research",
        "needs_live":True,
        "needs_tools":True,
        "verify":True,
        "depth":"deep",
        "capabilities":{
            "agent_runtime":True,
            "universal_retrieval":True,
            "autonomous_research":True,
            "retrieval":{"required":True,"unknown_terms":[]},
        },
        "requirement_contract":{"count":1,"hard_count":1,"density":"medium"},
    }
    task_graph_research=task_graph_build(
        "Research the current API behavior and verify it before answering.",
        task_graph_research_decision,
        file_names=[],
        has_project=False,
    )
    task_graph_failed=task_graph_reconcile(
        task_graph_research,
        {
            "planned":["autonomous_research"],
            "executed":[],
            "research":{"ok":False,"read_count":0,"source_count":0},
            "evidence_contract":{
                "retrieval":{"read_page_count":0,"explicit_browser_pages_read":0},
                "structured_live_data":False,
                "runtime_execution":{"verified_success":False},
            },
            "evidence_sufficiency":{
                "sufficient":False,
                "gaps":["live_source_evidence"],
            },
        },
        task_graph_research_decision,
    )
    task_graph_recovery=task_graph_recovery_decision(
        task_graph_failed,
        task_graph_research_decision,
        has_files=False,
    )
    task_graph_recovery_marked=task_graph_mark_recovery(task_graph_failed)
    task_graph_recovered=task_graph_reconcile(
        task_graph_recovery_marked,
        {
            "planned":["autonomous_research"],
            "executed":["autonomous_research"],
            "research":{"ok":True,"read_count":2,"source_count":3},
            "evidence_contract":{
                "retrieval":{"read_page_count":2,"explicit_browser_pages_read":0},
                "structured_live_data":False,
                "runtime_execution":{"verified_success":False},
            },
            "evidence_sufficiency":{
                "sufficient":True,
                "gaps":[],
            },
        },
        task_graph_research_decision,
    )

    task_graph_dead_decision={
        "difficulty":5,
        "profile":"analysis",
        "needs_live":False,
        "needs_tools":True,
        "verify":True,
        "depth":"deep",
        "capabilities":{"agent_runtime":True,"computer_requested":True},
        "requirement_contract":{"count":0,"hard_count":0,"density":"none"},
    }
    task_graph_dead=task_graph_reconcile(
        task_graph_build(
            "Inspect the connected computer and verify the observed state.",
            task_graph_dead_decision,
            file_names=[],
            has_project=False,
        ),
        {
            "planned":["computer_runtime"],
            "executed":[],
            "evidence_contract":{
                "retrieval":{"read_page_count":0,"explicit_browser_pages_read":0},
                "computer_observation_verified":False,
                "runtime_execution":{"verified_success":False},
            },
            "evidence_sufficiency":{
                "sufficient":False,
                "gaps":["computer_observation"],
            },
        },
        task_graph_dead_decision,
    )

    arena_memory_source="arena-memory-eval-source"
    arena_memory_restored="arena-memory-eval-restored"
    set_model_score(arena_memory_source,"main",100,.21,8)
    set_model_score(arena_memory_source,"coding",100,.19,3)
    set_model_score(arena_memory_source,"certification",100,.20,6)
    set_model_score(arena_memory_source,"shadow_coding",66.67,.0,3)
    set_model_score(arena_memory_source,"quality_screen",91.7,.18,12)
    arena_memory_snapshot=export_model_scores([arena_memory_source],30)
    arena_memory_rows=[]
    for _row in arena_memory_snapshot.get("rows",[]):
        _copy=dict(_row)
        _copy["model"]=arena_memory_restored
        arena_memory_rows.append(_copy)
    arena_memory_restore=import_model_scores(
        {"version":"R23-ARENA-SNAPSHOT-1","rows":arena_memory_rows},
        [arena_memory_restored],
        30,
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

    weak_live_out={
        "research":{"sources":[
            {"id":"R1","url":"https://example.com/snippet","read":False},
            {"id":"R2","url":"https://example.org/snippet","read":False},
        ]},
        "executed":["universal_retrieval"],
        "errors":[],
    }
    weak_live_contract=agent_evidence_contract(weak_live_out)
    weak_live_sufficiency=agent_evidence_sufficiency(
        weak_live_out,
        {"needs_live":True,"capabilities":{"universal_retrieval":True}},
        contract=weak_live_contract,
        depth="smart",
    )
    read_live_out={
        "research":{"sources":[
            {"id":"R1","url":"https://example.com/read","read":True},
            {"id":"R2","url":"https://example.org/snippet","read":False},
        ]},
        "executed":["universal_retrieval"],
        "errors":[],
    }
    read_live_contract=agent_evidence_contract(read_live_out)
    read_live_sufficiency=agent_evidence_sufficiency(
        read_live_out,
        {"needs_live":True,"capabilities":{"universal_retrieval":True}},
        contract=read_live_contract,
        depth="smart",
    )
    deep_one_read_sufficiency=agent_evidence_sufficiency(
        read_live_out,
        {"needs_live":True,"capabilities":{"universal_retrieval":True,"autonomous_research":True}},
        contract=read_live_contract,
        depth="deep",
    )
    deep_two_read_out={
        "research":{"sources":[
            {"id":"R1","url":"https://example.com/read","read":True},
            {"id":"R2","url":"https://example.org/read","read":True},
        ]},
        "executed":["autonomous_research"],
        "errors":[],
    }
    deep_two_read_contract=agent_evidence_contract(deep_two_read_out)
    deep_two_read_sufficiency=agent_evidence_sufficiency(
        deep_two_read_out,
        {"needs_live":True,"capabilities":{"universal_retrieval":True,"autonomous_research":True}},
        contract=deep_two_read_contract,
        depth="deep",
    )
    unverified_code_sufficiency=agent_evidence_sufficiency(
        {
            "executed":["code_test_fix_retest"],
            "code_loop":{"ok":True,"verified":False},
        },
        {"verify":True,"capabilities":{"code_fix_loop":True}},
        depth="smart",
    )
    verified_code_sufficiency=agent_evidence_sufficiency(
        {
            "executed":["code_test_fix_retest"],
            "code_loop":{"ok":True,"verified":True},
        },
        {"verify":True,"capabilities":{"code_fix_loop":True}},
        depth="smart",
    )

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
                  and reasoning_effort_for_depth("fast")=="low"
                  and reasoning_effort_for_depth("smart")=="medium"
                  and reasoning_effort_for_depth("deep")=="high"
                  and reasoning_effort_for_depth("apex")=="high"
                  and reasoning_effort_for_route("knowledge")=="medium"
                  and reasoning_effort_for_route("deep")=="high"
                  and reasoning_effort_for_route("apex")=="high"
                  and reasoning_effort_for_route("review-synthesis")=="high"
                  and reasoning_completion_budget("fast",180)==180
                  and reasoning_completion_budget("smart",180)>=900
                  and reasoning_completion_budget("deep",180)>=1800
                  and reasoning_completion_budget("apex",180)>=3000
                  and "counterexample" in reasoning_contract({"depth":"deep"}).lower()
                  and "two plausible" in reasoning_contract({"depth":"apex"}).lower()
                  and brain_status().get("provider_reasoning_effort") is True
                  and brain_status().get("reasoning_budget_decoupled_from_visible_brevity") is True
                  and brain_status().get("confidence_governor") is True
                  and brain_status().get("requirement_contract") is True
                  and brain_status().get("task_graph") is True
                  and task_graph_status().get("bounded_replanning") is True
                  and task_graph_status().get("max_recovery_passes")==1
                  and task_graph_simple.get("active") is False
                  and task_graph_hard.get("active") is True
                  and len(task_graph_hard.get("nodes") or [])>=4
                  and any(
                      "map_dependencies" in (x.get("depends_on") or [])
                      for x in task_graph_hard.get("nodes") or []
                      if x.get("id")=="execute_verify"
                  )
                  and task_graph_failed.get("replanned") is True
                  and task_graph_failed.get("recovery_kind")=="research"
                  and task_graph_failed.get("revision")==1
                  and "understand" in task_graph_failed.get("completed_nodes",[])
                  and task_graph_recovery is not None
                  and task_graph_recovery.get("depth")=="apex"
                  and task_graph_recovery.get("capabilities",{}).get("autonomous_research") is True
                  and task_graph_recovered.get("recovery_attempted") is True
                  and "gather_evidence" in task_graph_recovered.get("completed_nodes",[])
                  and "recover_research" in task_graph_recovered.get("completed_nodes",[])
                  and task_graph_recovered.get("dead_end") is False
                  and task_graph_dead.get("dead_end") is True
                  and "computer observation" in task_graph_dead.get("dead_end_reason","")
                  and task_graph_dead.get("completion_proof",{}).get("unresolved")
                  and requirement_contract.get("count",0)>=4
                  and requirement_contract.get("hard_count",0)>=3
                  and requirement_contract.get("density")=="high"
                  and requirement_plan.get("verify") is True
                  and requirement_plan.get("prompt_policy",{}).get("include_requirement_contract") is True
                  and requirement_plan.get("prompt_policy",{}).get("include_verification_directive") is True
                  and "RONN REQUIREMENT CONTRACT" in requirement_prompt
                  and "/v1/chat" in requirement_prompt
                  and "Only return JSON" in requirement_prompt
                  and confidence_status().get("enabled") is True
                  and confidence_low_result.get("score",1)<.38
                  and confidence_low_result.get("applied") is True
                  and confidence_low.get("depth")=="apex"
                  and confidence_low.get("verify") is True
                  and confidence_low.get("use_council") is True
                  and confidence_low.get("second_pass") is False
                  and confidence_low.get("prompt_policy",{}).get("include_verification_directive") is True
                  and confidence_fast_result.get("reason")=="explicit_mode_preserved"
                  and confidence_fast.get("depth")=="fast"
                  and confidence_fast.get("verify") is False
                  and confidence_fast.get("use_council") is False
                  and confidence_high_result.get("level")=="high"
                  and confidence_high_result.get("applied") is False
                  and confidence_high.get("depth")=="smart"
                  and confidence_high.get("verify") is False
                  and arena_domain_signal([
                      domain_models["or_nemotron"],domain_models["nvidia"],domain_models["smart"]
                  ],"coding")["ready"]
                  and domain_code_route[0]==domain_models["or_nemotron"]
                  and domain_code_plan.get("main_brain_domain_arena",{}).get("domain")=="coding"
                  and arena_challenger_signal(
                      challenger_models["or_deepseek"],"coding"
                  )["eligible"]
                  and arena_shadow_signal(
                      challenger_models["or_deepseek"],"coding"
                  )["ready"]
                  and arena_challenger_signal(
                      challenger_models["or_qwen"],"coding"
                  )["certified"]
                  and not arena_challenger_signal(
                      challenger_models["or_qwen"],"coding"
                  )["eligible"]
                  and arena_challenger_signal(
                      challenger_models["or_qwen"],"coding"
                  )["reason"]=="awaiting_production_shadow_trials"
                  and challenger_route[0]==challenger_models["or_deepseek"]
                  and challenger_pair.get("roles",[])[1]=="certified_shadow_challenger"
                  and challenger_pair.get("models",[])[1]==challenger_models["or_deepseek"]
                  and challenger_plan.get("main_brain_challengers",{}).get(
                      challenger_models["or_deepseek"],{}
                  ).get("eligible") is True
                  and challenger_plan.get("main_brain_challengers",{}).get(
                      challenger_models["or_qwen"],{}
                  ).get("eligible") is False
              )),

        _case("agent runtime exposes real tools with selective main-brain arbitration","2_full_agent_runtime",
              lambda:bool(
                  (lambda s:s.get("browser") and s.get("controlled_code_execution") and s.get("computer_adapter"))(agent_status())
                  and tool_arbiter_status().get("selective")
                  and not tool_should_arbitrate(
                      arbiter_simple,
                      has_files=False,
                      has_images=False,
                      has_project=False,
                      agent_mode=True,
                  )
                  and not tool_should_arbitrate(
                      arbiter_weather,
                      has_files=False,
                      has_images=False,
                      has_project=False,
                      agent_mode=True,
                  )
                  and arbiter_url.get("capabilities",{}).get("browser_url") is True
                  and arbiter_url.get("capabilities",{}).get("agent_runtime") is True
                  and not tool_should_arbitrate(
                      arbiter_url,
                      has_files=False,
                      has_images=False,
                      has_project=False,
                      agent_mode=True,
                  )
                  and arbiter_ambiguous.get("capabilities",{}).get("code_fix_loop") is False
                  and arbiter_ambiguous.get("capabilities",{}).get("world_model") is False
                  and tool_should_arbitrate(
                      arbiter_ambiguous,
                      has_files=True,
                      has_images=False,
                      has_project=True,
                      agent_mode=True,
                  )
                  and arbiter_high.get("accepted") is True
                  and arbiter_applied.get("needs_tools") is True
                  and arbiter_applied.get("verify") is True
                  and arbiter_applied.get("capabilities",{}).get("code_fix_loop") is True
                  and arbiter_applied.get("tool_arbitration",{}).get("action")=="code_execute"
                  and arbiter_low.get("accepted") is False
                  and arbiter_low_applied.get("needs_live") is False
                  and arbiter_low_applied.get("tool_arbitration",{}).get("action")=="none"
              )),

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

        _case("long context stays current-state aware and file prompts stay deduplicated","5_long_context_compression",
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
                  and (lambda p:
                      p["include_files_in_compiler"] is False
                      and p["include_current_file_kb"] is False
                      and p["include_project_graph"] is False
                      and p["include_context_manifest"] is False
                      and p["project_index_mode"]=="compact"
                      and p["raw_file_source"]=="user_message"
                  )(prompt_context_policy(has_files=True,followup=False,project_scope=True))
                  and (lambda p:
                      p["include_current_file_kb"] is True
                      and p["include_project_graph"] is True
                  )(prompt_context_policy(has_files=False,followup=True,project_scope=True))
              )),

        _case("evaluation lab and Arena evidence survive portable restore","6_real_evaluation_lab",
              lambda:bool(
                  capability_status().get("feature_count")==11
                  and len(capability_status().get("features",{}))==11
                  and arena_memory_restore.get("ok")
                  and arena_memory_restore.get("imported",0)>=5
                  and arena_routing_signal([arena_memory_restored])["ready"]
                  and arena_domain_signal([arena_memory_restored],"coding")["ready"]
                  and arena_shadow_signal(arena_memory_restored,"coding")["ready"]
                  and quality_signal([arena_memory_restored],"screen")["ready"]
                  and arena_challenger_signal(arena_memory_restored,"coding")["eligible"]
                  and len(QUALITY_CASES)==36
                  and len(quality_cases_for_tier("screen"))==12
                  and len(quality_cases_for_tier("standard"))==24
                  and len(quality_cases_for_tier("deep"))==36
                  and len({x["category"] for x in QUALITY_CASES})==6
                  and all(sum(1 for x in QUALITY_CASES if x["category"]==cat)==6
                          for cat in {x["category"] for x in QUALITY_CASES})
                  and quality_grade(QUALITY_CASES[0],QUALITY_CASES[0]["expected"])
                  and not quality_grade(QUALITY_CASES[0],"definitely wrong")
                  and quality_status().get("manual_only") is True
                  and quality_status().get("auto_run") is False
                  and quality_shared_signal.get("ready") is True
                  and quality_shared_signal.get("tier")=="screen"
                  and quality_route[0]==quality_models["nvidia"]
                  and quality_runner_result.get("signal",{}).get("ready") is True
                  and quality_runner_result.get("signal",{}).get("tier")=="deep"
                  and quality_runner_result.get("cases_per_model")==36
                  and quality_runner_result.get("provider_calls")==36
                  and quality_runner_result.get("results",[{}])[0].get("score")==100.0
                  and quality_runner_result.get("results",[{}])[0].get("complete") is True
              )),

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

        _case("autonomous research, recovery, and evidence sufficiency stay evidence-bound","10_autonomous_research",
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
                  and agent_status().get("bounded_research_recovery") is True
                  and agent_status().get("evidence_sufficiency_gate") is True
                  and weak_live_sufficiency["sufficient"] is False
                  and "live_source_evidence" in weak_live_sufficiency["gaps"]
                  and read_live_sufficiency["sufficient"] is True
                  and deep_one_read_sufficiency["sufficient"] is False
                  and deep_two_read_sufficiency["sufficient"] is True
                  and unverified_code_sufficiency["sufficient"] is False
                  and "runtime_verification" in unverified_code_sufficiency["gaps"]
                  and verified_code_sufficiency["sufficient"] is True
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
