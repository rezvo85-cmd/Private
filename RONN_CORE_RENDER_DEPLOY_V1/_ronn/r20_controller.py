from __future__ import annotations
import json, os, re
from typing import Any

R20_VERSION="R20-CONTROLLER-1"
PROFILES={"chat","knowledge","coding","mathscience","writing","research","creative","analysis"}
DEPTHS={"fast","smart","deep","apex"}
SPECIALISTS={"general","coding","reasoning","research","vision","writing","creative"}

try:
    from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel, set_tracing_disabled
    AGENTS_SDK_AVAILABLE=True
    try:set_tracing_disabled(disabled=True)
    except TypeError:set_tracing_disabled(True)
except Exception:
    Agent=Runner=AsyncOpenAI=OpenAIChatCompletionsModel=None
    AGENTS_SDK_AVAILABLE=False

def _clean(v,limit=1200):
    return re.sub(r"\s+"," ",str(v or "")).strip()[:limit]

def _profile(message,file_names):
    low=(message or "").lower(); names=" ".join(file_names or []).lower(); hay=low+" "+names
    if any(x in hay for x in ("code","script","debug","api","python","javascript","typescript","html","css",".py",".js",".ts",".json","database","backend","frontend","github","server","client","exception","stack trace")): return "coding"
    if any(x in low for x in ("equation","calculate","geometry","algebra","probability","physics","chemistry","biology","formula","solve for","math")): return "mathscience"
    if any(x in low for x in ("rewrite","paraphrase","essay","paragraph","thesis","grammar","email","caption","summarize this","proofread")): return "writing"
    if any(x in low for x in ("research","sources","search the web","look this up","latest","current","today","right now","news","weather","price","standings")): return "research"
    if any(x in low for x in ("design","create","creative","idea","concept","logo","brand","story","worldbuilding","ui design","game idea")): return "creative"
    if any(x in low for x in ("analyze","compare","reason","architecture","tradeoff","plan","complex","deep","hard")): return "analysis"
    if re.match(r"^\s*(who|what|when|where|why|how|which|is|are|was|were|does|did|can)\b",low): return "knowledge"
    return "chat"

def _difficulty(message,file_count,has_project):
    low=(message or "").lower(); n=len(message or ""); score=1
    if n>180: score+=1
    if n>650: score+=1
    if file_count: score+=1
    if file_count>=4: score+=1
    if has_project: score+=1
    score+=sum(1 for x in ("full project","whole project","entire project","production","architecture","multi-step","debug all","root cause","deploy","test and fix","make everything","complete system","whole system") if x in low)
    return max(1,min(score,8))

def _local_intent(message):
    low=re.sub(r"\s+"," ",(message or "").lower()).strip()
    return any(x in low for x in (
        "near me","nearby","closest","around me","close to me","in my area",
        "my location","use my location","see my location","current location","where am i",
        "restaurant near","restaurants near","restaurants around","food near","places to eat near","coffee near",
        "gas station near","store near","stores near","pharmacy near","hospital near","open near me",
        "recommend me restaurants","recommend restaurants"
    ))

def _natural_lookup_intent(message):
    low=re.sub(r"\s+"," ",str(message or "").lower()).strip()
    patterns=(
        r"\bcheck (?:that|this|it|those|these) out\b",
        r"\bcheck (?:that|this|it|those|these) (?:for me|online)\b",
        r"\b(?:can you |could you )?(?:find|look up|look into|check for|see if)\b",
        r"\bfind me\b",
        r"\bwhere (?:can|could) i (?:buy|get|find)\b",
        r"\bwhat(?:'s| is) new with\b",
    )
    return any(re.search(p,low,re.I) for p in patterns)


def _needs_live(message,profile):
    low=(message or "").lower()
    freshness=any(re.search(p,low,re.I) for p in (
        r"\b(?:today|tonight|right now|currently|latest|newest|this week|recent|recently|breaking)\b",
        r"\b(?:new release|new drop|just dropped|dropping|restock|restocked|restocking|in stock|sold out|available now)\b",
        r"\b(?:weather|forecast|news|score|standings|schedule|price today|stock price|who won|release date|current version|open now)\b",
    ))
    natural=_natural_lookup_intent(message) and profile not in {"creative","writing"}
    new_lookup=bool(re.search(r"\bnew\b",low) and natural and profile!="coding")
    return bool(profile=="research" or _local_intent(message) or freshness or natural or new_lookup)

def deterministic_plan(message,history=None,file_names=None,has_images=False,has_project=False,agent_mode=True,explicit_mode="auto"):
    history=history or []; file_names=file_names or []
    profile=_profile(message,file_names); difficulty=_difficulty(message,len(file_names),has_project); live=_needs_live(message,profile)
    low=(message or "").lower()
    verify=(profile=="coding" and (file_names or any(x in low for x in ("fix","debug","deploy","test","repair")))) or difficulty>=5 or any(x in low for x in ("make sure","verify","double check","accurate","correct","no errors","production ready","actually works"))
    specialist="vision" if has_images else {"coding":"coding","mathscience":"reasoning","analysis":"reasoning","research":"research","writing":"writing","creative":"creative"}.get(profile,"general")
    depth="fast" if difficulty<=1 and profile in {"chat","knowledge"} else ("smart" if difficulty<=3 else ("deep" if difficulty<=5 else "apex"))
    mode=(explicit_mode or "auto").lower()
    if mode!="auto" and mode in {"fast","deep","ultra","apex","max","live","creator"}:
        depth={"fast":"fast","deep":"deep","ultra":"deep","apex":"apex","max":"deep","live":"smart","creator":"deep"}[mode]
        if mode in {"live","max"}: live=True; profile="research"; specialist="research"
    tool_mode="live" if live else ("code" if profile=="coding" and file_names and any(x in low for x in ("run","test","debug","fix","repair","execute")) else ("files" if file_names else ("agent" if agent_mode and any(x in low for x in ("deploy","open","check","inspect","use ","go to ")) else "none")))
    return {"version":R20_VERSION,"profile":profile,"difficulty":difficulty,"depth":depth,"specialist":specialist,"needs_live":bool(live),"needs_tools":tool_mode!="none","tool_mode":tool_mode,"verify":bool(verify),"second_pass":bool(verify and difficulty>=3),"use_council":bool(difficulty>=6 and not live and not has_images),"memory_scope":"project" if has_project else ("conversation" if history else "general"),"followup":bool(history and re.match(r"^\s*(do that|continue|keep going|that one|the other one|fix it|same thing)\b",low)),"sdk_used":False,"controller_model":"","reason":"deterministic"}

def _provider():
    enabled=os.getenv("RONN_R20_AGENT_CONTROLLER","true").strip().lower() not in {"0","false","off","no"}
    if not enabled or not AGENTS_SDK_AVAILABLE:return None
    gk=(os.getenv("CLOUD_API_KEY","").strip() or os.getenv("GROQ_API_KEY","").strip())
    if gk:return os.getenv("CLOUD_API_BASE","https://api.groq.com/openai/v1").rstrip("/"),gk,os.getenv("RONN_CONTROLLER_MODEL",os.getenv("RONN_FAST_MODEL","openai/gpt-oss-20b")).strip()
    ok=os.getenv("OPENROUTER_API_KEY","").strip()
    if ok:return os.getenv("OPENROUTER_API_BASE","https://openrouter.ai/api/v1").rstrip("/"),ok,os.getenv("RONN_CONTROLLER_OPENROUTER_MODEL","qwen/qwen3.6-27b").strip()
    nk=os.getenv("NVIDIA_API_KEY","").strip()
    if nk:return os.getenv("NVIDIA_BASE_URL","https://integrate.api.nvidia.com/v1").rstrip("/"),nk,os.getenv("NVIDIA_MODEL","nvidia/nemotron-3-super-120b-a12b").strip()
    return None

def _json_obj(text):
    clean=re.sub(r"(?is)<think>.*?</think>|</?think>","",str(text or "")).strip()
    m=re.search(r"\`\`\`(?:json)?\s*([\s\S]*?)\`\`\`",clean,re.I)
    if m:clean=m.group(1).strip()
    a,b=clean.find("{"),clean.rfind("}")
    if a>=0 and b>a:clean=clean[a:b+1]
    try:
        x=json.loads(clean); return x if isinstance(x,dict) else None
    except Exception:return None

def _sdk_refine(base,message,history,file_names,has_images,has_project):
    p=_provider()
    if not p:return base
    base_url,key,model_name=p
    try:
        model=OpenAIChatCompletionsModel(model=model_name,openai_client=AsyncOpenAI(api_key=key,base_url=base_url))
        agent=Agent(name="RONN Controller",instructions=("Do not answer the user. Return ONE compact JSON object only. Decide task type and needed reasoning. Allowed profile: chat, knowledge, coding, mathscience, writing, research, creative, analysis. Allowed depth: fast, smart, deep, apex. Allowed specialist: general, coding, reasoning, research, vision, writing, creative. Keys: profile, depth, specialist, needs_live, verify, second_pass, use_council, reason. Set needs_live=true when the answer depends on current information, when the subject is niche or uncertain enough that web verification would materially improve reliability, or when the user asks to search/find/check something. Keep needs_live=false for ordinary stable common knowledge, pure writing, and tasks fully answerable from supplied files/context. Keep reason under 12 words. Prefer fast/simple unless deeper work is truly useful."),model=model)
        recent=[{"role":str(x.get("role") or ""),"content":_clean(x.get("content"),700)} for x in (history or [])[-6:] if str(x.get("role") or "") in {"user","assistant"} and _clean(x.get("content"),700)]
        prompt=json.dumps({"user_message":_clean(message,5000),"recent_history":recent,"files":(file_names or [])[:30],"has_images":has_images,"has_project_context":has_project,"preplan":{k:base[k] for k in ("profile","difficulty","depth","specialist","needs_live","verify")}},ensure_ascii=False)
        result=Runner.run_sync(agent,prompt,max_turns=1); data=_json_obj(getattr(result,"final_output",""))
        if not data:return base
        out=dict(base)
        if str(data.get("profile","")).lower() in PROFILES:out["profile"]=str(data["profile"]).lower()
        if str(data.get("depth","")).lower() in DEPTHS:out["depth"]=str(data["depth"]).lower()
        if str(data.get("specialist","")).lower() in SPECIALISTS:out["specialist"]=str(data["specialist"]).lower()
        for k in ("needs_live","verify","second_pass","use_council"):
            if k in data:
                out[k]=bool(base.get(k) or data[k]) if k=="needs_live" else bool(data[k])
        if has_images:out["specialist"]="vision"
        if out["needs_live"]:out.update({"profile":"research","specialist":"research","tool_mode":"live","needs_tools":True,"use_council":False})
        out.update({"sdk_used":True,"controller_model":model_name,"reason":_clean(data.get("reason"),120) or "sdk-refined"})
        return out
    except Exception as exc:
        out=dict(base); out["sdk_error"]=exc.__class__.__name__; return out

def plan(message,history=None,file_names=None,has_images=False,has_project=False,agent_mode=True,explicit_mode="auto"):
    base=deterministic_plan(message,history,file_names,has_images,has_project,agent_mode,explicit_mode)
    return base if (explicit_mode or "auto").lower()!="auto" else _sdk_refine(base,message,history or [],file_names or [],has_images,has_project)

def resolve_route(decision,providers,models):
    OR=bool(providers.get("openrouter")); NV=bool(providers.get("nvidia")); G=bool(providers.get("groq"))
    sp=decision.get("specialist"); depth=decision.get("depth")
    if sp=="vision":return (models["or_qwen"],"r20-vision") if OR else (models["vision"],"vision")
    if decision.get("needs_live"):
        if G:return (models["research"] if depth in {"deep","apex"} else models["live"],"research")
        if OR:return models["or_qwen"],"r20-current"
        if NV:return models["nvidia"],"r20-research"
        return models["smart"],"knowledge"
    if sp=="coding":
        if OR:return models["or_deepseek"],"r20-code"
        if NV:return models["nvidia"],"r20-code"
        return models["creator"],"creator"
    if sp=="reasoning":
        if OR:return models["or_nemotron"],"r20-reasoning"
        if NV:return models["nvidia"],"r20-reasoning"
        return models["smart"],"deep"
    if sp=="creative":
        if OR:return models["or_qwen"],"r20-creative"
        if NV:return models["nvidia"],"r20-creative"
        return models["creator"],"creator"
    if sp=="writing":
        return (models["or_qwen"],"r20-writing") if OR else (models["smart"],"knowledge")
    if depth=="apex":
        if OR:return models["or_nemotron"],"r20-apex"
        if NV:return models["nvidia"],"r20-apex"
        return models["smart"],"apex"
    if depth=="deep":
        if OR:return models["or_nemotron"],"r20-deep"
        if NV:return models["nvidia"],"r20-deep"
        return models["smart"],"deep"
    if depth=="smart":
        return (models["or_qwen"],"r20-smart") if OR else (models["smart"],"knowledge")
    return models["fast"],"fast"

def directive(decision):
    return ("RONN R20 CENTRAL CONTROLLER:\n"
        f"- Profile: {decision.get('profile')}\n- Reasoning depth: {decision.get('depth')}\n"
        f"- Specialist: {decision.get('specialist')}\n- Live evidence needed: {bool(decision.get('needs_live'))}\n"
        f"- Verification pass: {bool(decision.get('verify'))}\n- Memory scope: {decision.get('memory_scope')}\n"
        "This is the single routing decision for this turn. Older RONN modules may provide context, evidence, memories, tests, or review signals underneath it, but must not independently redefine the task or switch the route. Answer as one coherent RONN assistant.")

def status():
    p=_provider()
    return {"version":R20_VERSION,"central_controller":True,"agents_sdk_available":AGENTS_SDK_AVAILABLE,"agent_refinement_enabled":p is not None,"controller_model":p[2] if p else "","policy":"one-controller"}
