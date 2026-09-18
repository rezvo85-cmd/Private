import re, math, json, hashlib, time
from collections import Counter

FRESHNESS_WORDS = (
    "today","latest","current","now","recent","this week","this month","price",
    "news","weather","score","release","version","updated","newest"
)

DOMAIN_HINTS = {
    "coding": ("code","python","javascript","typescript","api","backend","frontend","database","debug","script"),
    "research": ("research","source","latest","compare","evidence","study","news"),
    "mathscience": ("math","equation","physics","chemistry","biology","calculate","probability"),
    "writing": ("write","rewrite","essay","paragraph","email","summary","tone"),
    "creative": ("design","creative","idea","story","game","brand","ui","concept"),
    "analysis": ("analyze","reason","strategy","architecture","tradeoff","plan","complex"),
}

def _clean(s):
    return re.sub(r"\s+"," ",str(s or "")).strip()

def _sentences(text):
    return [x.strip(" \t-•") for x in re.split(r"(?<=[.!?])\s+|\n+", text or "") if x.strip()]

def specification_compile(message: str):
    text=_clean(message)
    goals=[]
    constraints=[]
    deliverables=[]
    negatives=[]
    for s in _sentences(message):
        low=s.lower()
        if any(x in low for x in ("don't ","do not ","without ","avoid ","never ")):
            negatives.append(s[:600])
        if any(x in low for x in ("must ","need ","needs ","require","keep ","use ","make sure","exactly ")):
            constraints.append(s[:600])
        if any(x in low for x in ("make ","build ","create ","write ","design ","analyze ","research ","fix ","compare ","generate ")):
            deliverables.append(s[:600])
    if text:
        goals=[text[:1200]]
    return {
        "goal": goals[0] if goals else "",
        "deliverables": list(dict.fromkeys(deliverables))[:24],
        "constraints": list(dict.fromkeys(constraints))[:24],
        "negative_constraints": list(dict.fromkeys(negatives))[:16],
    }

def assumption_scan(message: str):
    assumptions=[]
    for s in _sentences(message):
        low=s.lower()
        if any(x in low for x in ("probably","likely","should be","i think","assume","assuming","maybe")):
            assumptions.append({"text":s[:500],"status":"unverified"})
    return assumptions[:20]

def information_gaps(message: str, profile: str, has_files=False, project_context=False):
    low=(message or "").lower()
    gaps=[]
    if any(x in low for x in FRESHNESS_WORDS):
        gaps.append({"gap":"fresh_information","best_action":"live_research","importance":"high"})
    if profile=="coding" and any(x in low for x in ("fix this","debug this","why is this broken")) and not has_files:
        gaps.append({"gap":"source_or_error_context","best_action":"inspect_attached_code_or_error","importance":"high"})
    if any(x in low for x in ("compare","best","which is better")):
        gaps.append({"gap":"decision_criteria","best_action":"infer_from_context_or_state_assumptions","importance":"medium"})
    if len((message or "").strip()) < 12 and profile not in ("chat","knowledge"):
        gaps.append({"gap":"underspecified_goal","best_action":"use_conversation_context_before_clarifying","importance":"medium"})
    return gaps[:10]

def uncertainty_ledger(message: str, profile: str):
    low=(message or "").lower()
    items=[]
    if any(x in low for x in FRESHNESS_WORDS):
        items.append({"claim_type":"time_sensitive","status":"requires_live_evidence"})
    if any(x in low for x in ("estimate","guess","predict","future","likely")):
        items.append({"claim_type":"prediction","status":"inference_not_fact"})
    if profile in ("coding","analysis") and any(x in low for x in ("works","guaranteed","perfect","production")):
        items.append({"claim_type":"outcome","status":"requires_execution_or_test_evidence"})
    return items[:12]

def choose_specialists(profile: str, message: str, difficulty: int):
    low=(message or "").lower()
    team=["orchestrator"]
    mapping={
        "coding":["software_engineer","debugger","test_engineer","architecture_reviewer"],
        "research":["researcher","fact_checker","evidence_reviewer"],
        "analysis":["deep_reasoner","causal_analyst","adversarial_reviewer"],
        "mathscience":["math_science_specialist","verification_reviewer"],
        "creative":["creative_director","product_designer","critic"],
        "writing":["writer","editor"],
        "knowledge":["knowledge_specialist","fact_checker"],
        "chat":["conversation"],
    }
    for x in mapping.get(profile,["generalist"]):
        if x not in team: team.append(x)
    if any(x in low for x in ("data","csv","spreadsheet","dataset","statistics")):
        team += ["data_analyst"]
    if difficulty >= 5:
        team += ["independent_critic","outcome_evaluator"]
    return list(dict.fromkeys(team))[:8]

def strategy_search(profile: str, difficulty: int, gaps, has_files=False):
    strategies=[]
    if difficulty <= 1:
        strategies.append({"name":"direct","score":0.9,"why":"Low complexity"})
    else:
        strategies.append({"name":"plan_solve_verify","score":0.92,"why":"General robust path"})
    if profile=="research":
        strategies.append({"name":"retrieve_compare_synthesize","score":0.95,"why":"Evidence-dependent task"})
    if profile=="coding":
        strategies.append({"name":"inspect_architect_implement_static_check","score":0.95,"why":"Engineering task"})
    if difficulty >= 5:
        strategies.append({"name":"multi_candidate_critic_synthesis","score":0.97,"why":"High complexity benefits from independent attempts"})
    if any(g.get("gap")=="fresh_information" for g in gaps):
        strategies.append({"name":"live_research_first","score":0.99,"why":"Fresh evidence required"})
    strategies.sort(key=lambda x:x["score"],reverse=True)
    return strategies[:5]

def budget_policy(difficulty: int, profile: str, has_files=False):
    # Budget is a routing policy, not hidden reasoning.
    if difficulty >= 6:
        tier="apex"
        passes=3
    elif difficulty >= 4:
        tier="deep"
        passes=2
    elif difficulty >= 2:
        tier="balanced"
        passes=1
    else:
        tier="fast"
        passes=1
    if profile=="research": tier="tools"
    return {
        "tier":tier,
        "passes":passes,
        "context_budget_chars": 36000 if has_files or difficulty>=4 else 18000,
        "verification_required": difficulty>=3,
        "adversarial_review": difficulty>=5,
    }

def permission_class(action_text: str):
    low=(action_text or "").lower()
    if any(x in low for x in ("delete all","format drive","disable antivirus","password","api key","credential","publish account","powershell","cmd.exe","shell command")):
        return {"class":"blocked_or_high_risk","approval":"required_or_disallowed"}
    if any(x in low for x in ("send email","post","purchase","upload public","delete file","change settings")):
        return {"class":"external_side_effect","approval":"required"}
    return {"class":"read_or_benign","approval":"context_dependent"}

def recovery_hierarchy():
    return [
        "validate_input",
        "retry_once_if_transient",
        "adjust_parameters",
        "switch_model_or_tool",
        "revise_hypothesis",
        "use_available_context_or_evidence",
        "ask_user_only_if_material_information_is_missing",
    ]

def context_score(query: str, text: str):
    qw=set(re.findall(r"[a-z0-9_]{3,}",(query or "").lower()))
    tw=set(re.findall(r"[a-z0-9_]{3,}",(text or "").lower()))
    overlap=len(qw & tw)
    return overlap + min(3, len(text or "")/4000)

def compile_context(query: str, project_context: str, files, memory_block: str="", brain_block: str="", max_chars=30000):
    candidates=[]
    if project_context:
        candidates.append(("project",project_context,context_score(query,project_context)+3))
    if memory_block:
        candidates.append(("memory",memory_block,context_score(query,memory_block)+2))
    if brain_block:
        candidates.append(("project_brain",brain_block,context_score(query,brain_block)+4))
    for f in files or []:
        name=getattr(f,"name","file")
        content=getattr(f,"content","")
        candidates.append((f"file:{name}",content,context_score(query,name+" "+content)+3))
    candidates.sort(key=lambda x:x[2],reverse=True)
    out=[]
    used=0
    manifest=[]
    for label,text,score in candidates:
        text=str(text or "")
        remaining=max_chars-used
        if remaining<=500: break
        piece=text[:remaining]
        if piece.strip():
            out.append(f"--- {label} ---\n{piece}")
            used+=len(piece)
            manifest.append({"source":label,"score":round(score,2),"chars":len(piece)})
    return {"text":"\n\n".join(out),"manifest":manifest,"chars":used}

def metacognition_state(message: str, profile: str, difficulty: int, has_files=False, has_project=False):
    gaps=information_gaps(message,profile,has_files,has_project)
    spec=specification_compile(message)
    return {
        "specification":spec,
        "assumptions":assumption_scan(message),
        "information_gaps":gaps,
        "uncertainty":uncertainty_ledger(message,profile),
        "specialists":choose_specialists(profile,message,difficulty),
        "strategies":strategy_search(profile,difficulty,gaps,has_files),
        "budget":budget_policy(difficulty,profile,has_files),
        "recovery":recovery_hierarchy(),
    }

def os_directive(state: dict):
    spec=state.get("specification",{})
    gaps=state.get("information_gaps",[])
    unc=state.get("uncertainty",[])
    specialists=", ".join(state.get("specialists",[]))
    strategy=(state.get("strategies") or [{"name":"direct"}])[0]["name"]
    return f"""RONN COGNITIVE OPERATING SYSTEM:
- Goal: {spec.get("goal","")[:800]}
- Selected strategy: {strategy}
- Specialist roles available for this task: {specialists}
- Maintain an explicit internal distinction between VERIFIED, INFERRED, ASSUMED, and UNKNOWN information.
- Challenge high-impact assumptions before relying on them.
- Detect contradictions between user instructions, retrieved context, files, memories, and live evidence. Prefer the newest explicit user instruction, and surface material conflicts.
- Identify missing information by expected value: use a tool/source when it can resolve the gap; ask the user only when the missing detail materially changes the result and cannot be retrieved.
- For difficult decisions, privately explore multiple viable solution branches and prune weak ones before selecting the final approach.
- For causal questions, separate correlation, mechanism, intervention, and alternative explanations.
- For time-sensitive claims, require fresh evidence instead of stale memory.
- For hard tasks, use plan -> solve -> adversarial check -> repair -> outcome verification.
- Evaluate whether the USER'S requested outcome is satisfied, not merely whether RONN completed its own plan.
- Never reveal private chain-of-thought. You may provide concise conclusions, assumptions, evidence summaries, checks, and decision rationale.
- Recovery order on failure: {" -> ".join(state.get("recovery",[]))}
- Current information gaps: {json.dumps(gaps,ensure_ascii=False)[:1800]}
- Current uncertainty flags: {json.dumps(unc,ensure_ascii=False)[:1600]}
"""
