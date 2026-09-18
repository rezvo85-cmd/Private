"""RONN R11 Reliability Intelligence.

Exactly 600 active task/reliability signals (30 dimensions x 20 signals)
influence routing, context handling, verification, freshness, uncertainty
discipline, and response planning. These are heuristics, not 600 AI models.
"""
from __future__ import annotations

import json
import re
from collections import Counter

SIGNALS = {
    "factual": ["who","what","when","where","which","how many","how much","is it true","does","did","can","definition","meaning","fact","facts","explain","tell me about","information","accurate","correct"],
    "freshness": ["today","right now","currently","current","latest","recent","this week","this month","this year","newest","updated","update","still","now","2026","release","version","price","schedule","available"],
    "ambiguity": ["this","that","it","they","them","there","same thing","like before","do that","fix that","change it","make it","what happened","why not","again","the other one","that one","this one","you know","whatever"],
    "followup": ["do it","continue","keep going","fix it","try again","now do","what about","and then","next","same","again","more","less","better","worse","why","what happened","use that","keep it","change that"],
    "correction": ["wrong","not right","incorrect","you missed","actually","no i mean","i meant","stop saying","that's not","that is not","you forgot","fix your answer","recheck","double check","verify again","mistake","error in your answer","correct yourself","redo","re-evaluate"],
    "uncertainty": ["maybe","probably","likely","possibly","i think","not sure","unsure","guess","estimate","approximately","around","roughly","seems","appears","could be","might be","confidence","uncertain","unknown","depends"],
    "research": ["research","look up","search","find out","sources","source","cite","citation","evidence","official","documentation","docs","study","paper","article","news","compare sources","verify online","web","internet"],
    "source_quality": ["primary source","official source","government","documentation","manual","specification","release notes","peer reviewed","study","dataset","original source","direct source","authoritative","reliable source","credible","cross-check","corroborate","independent source","publisher","date published"],
    "coding": ["code","script","function","class","api","backend","frontend","python","javascript","typescript","html","css","json","database","repository","github","server","client","module","package"],
    "debugging": ["bug","error","broken","not working","fails","failure","crash","traceback","exception","fix","debug","issue","problem","stuck","doesn't work","does not work","wrong output","unexpected","root cause","regression"],
    "architecture": ["architecture","system design","structure","components","service","microservice","module boundaries","interface","dependency","workflow","pipeline","scalable","maintainable","design pattern","data flow","state machine","orchestration","integration","contract","schema"],
    "security": ["security","secure","secret","token","api key","password","auth","authentication","authorization","permission","privacy","encrypt","encryption","vulnerability","attack","injection","xss","csrf","credential","access control"],
    "performance": ["performance","slow","fast","latency","speed","optimize","optimization","memory usage","cpu","gpu","throughput","bottleneck","cache","caching","load time","efficient","efficiency","scale","scaling","timeout"],
    "testing": ["test","tests","testing","verify","validation","validate","unit test","integration test","e2e","regression","assert","benchmark","check","reproduce","proof","pass","fail","coverage","runtime test","static check"],
    "deployment": ["deploy","deployment","production","release","publish","hosting","render","vercel","server","cloud","environment variable","env","build command","start command","domain","ssl","https","rollback","live site","health check"],
    "math": ["calculate","math","equation","solve","algebra","geometry","probability","statistics","percent","percentage","ratio","fraction","derivative","integral","matrix","formula","number","average","median","graph"],
    "science": ["physics","chemistry","biology","science","experiment","hypothesis","molecule","atom","force","energy","cell","genetics","reaction","temperature","mass","velocity","acceleration","evidence","theory","measurement"],
    "writing": ["write","rewrite","paragraph","essay","email","message","caption","grammar","tone","wording","professional","natural","shorter","longer","clearer","edit","proofread","thesis","introduction","conclusion"],
    "summarization": ["summarize","summary","short version","tl;dr","main point","key points","overview","recap","condense","brief","in short","what happened","explain simply","simplify","break down","gist","takeaways","highlights","important parts","quick summary"],
    "planning": ["plan","roadmap","steps","step by step","strategy","schedule","milestone","timeline","next steps","how should","what should i do","project plan","launch plan","implementation plan","approach","sequence","priority","prioritize","organize","workflow"],
    "decision": ["choose","decision","decide","which should","should i","recommend","best option","tradeoff","pros and cons","worth it","better choice","pick","option","alternative","compare","risk","benefit","cost","downside","upside"],
    "comparison": ["compare","versus","vs","difference","better than","worse than","similar","same","different","advantages","disadvantages","pros","cons","side by side","contrast","which is better","alternative","option a","option b","tradeoff"],
    "creative": ["create","design","idea","concept","creative","story","character","game idea","mechanic","logo","brand","visual","style","name ideas","brainstorm","worldbuilding","moveset","ability","theme","mockup"],
    "multimodal": ["image","photo","picture","screenshot","video","audio","screen","look at this","see this","attached image","camera","visual","diagram","chart","graph","scan","frame","pixel","resolution","ocr"],
    "files": ["file","files","folder","zip","pdf","docx","xlsx","pptx","attachment","upload","download","document","project files","source file","read this","open this","analyze file","extract","archive","directory"],
    "project_memory": ["remember","memory","project","previous","before","earlier","last time","we did","we made","our project","continue project","keep consistent","same design","same code","prior decision","history","context","past chat","don't forget","use previous"],
    "constraints": ["must","cannot","can't","do not","don't","only","exactly","at least","at most","under","over","without","keep","preserve","avoid","required","requirement","constraint","limit","no more"],
    "verification": ["verify","verified","reliable","accuracy","accurate","double check","fact check","prove","evidence","confirm","confirmation","test it","make sure","don't guess","do not guess","certain","confidence","source check","validate","trustworthy"],
    "causal_reasoning": ["why","cause","because","reason","root cause","what caused","how did","leads to","results in","effect","impact","mechanism","chain","dependency","trigger","consequence","due to","explain why","relationship","correlation"],
    "synthesis": ["combine","synthesize","put together","merge","integrate","overall","big picture","across","multiple","all of this","connect","relationship","summary and recommendation","final answer","conclusion","complete answer","comprehensive","whole picture","bring together","unify"],
}
SIGNAL_COUNT = sum(len(v) for v in SIGNALS.values())
assert SIGNAL_COUNT == 600

_STRONG_VERIFY = {"verification","security","testing","deployment","correction","source_quality"}
_HARD = {"coding","debugging","architecture","security","math","science","decision","causal_reasoning","synthesis"}
_CONTEXT = {"ambiguity","followup","project_memory","constraints","correction"}
_LIVE = {"freshness","research","source_quality"}

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()

def _contains(text: str, phrase: str) -> bool:
    if len(phrase) <= 4 and phrase.isalnum():
        return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None
    return phrase in text

def _history_text(history) -> str:
    rows=[]
    for item in list(history or [])[-20:]:
        if isinstance(item, dict):
            rows.append(str(item.get("content") or ""))
        else:
            rows.append(str(item or ""))
    return _norm(" ".join(rows))

def r11_preflight(message: str, history=None, profile: str="chat", difficulty: int=0,
                  has_files: bool=False, has_images: bool=False, project_context: str="") -> dict:
    text=_norm(message)
    hist=_history_text(history)
    matched=[]
    counts=Counter()
    for category, signals in SIGNALS.items():
        for idx, phrase in enumerate(signals, 1):
            if _contains(text, phrase):
                matched.append({"id":f"{category}:{idx:02d}","category":category,"signal":phrase})
                counts[category]+=1

    words=text.split()
    short_followup = len(words) <= 12 and (
        counts["followup"] > 0 or counts["ambiguity"] > 0 or
        any(x in text for x in ("do it","fix it","continue","again","what about","why"))
    )
    context_dependency = sum(counts[x] for x in _CONTEXT) + (3 if short_followup and hist else 0)
    live_score = sum(counts[x] for x in _LIVE)
    verify_score = sum(counts[x] for x in _STRONG_VERIFY)
    hard_score = sum(counts[x] for x in _HARD)
    evidence_score = counts["factual"] + counts["research"] + counts["source_quality"] + counts["freshness"]
    uncertainty_score = counts["uncertainty"]

    if has_files:
        hard_score += 2
        context_dependency += 1
    if has_images:
        hard_score += 2
    if project_context:
        context_dependency += 2
    hard_score += max(0, int(difficulty or 0) // 2)

    if live_score >= 1:
        tier="research"
    elif hard_score >= 10 or verify_score >= 6:
        tier="apex"
    elif hard_score >= 5 or verify_score >= 3:
        tier="deep"
    elif hard_score >= 2 or evidence_score >= 3:
        tier="smart"
    else:
        tier="fast"

    second_pass = bool(
        verify_score >= 2 or
        (hard_score >= 5 and counts["verification"] >= 1) or
        counts["correction"] >= 1 or
        counts["security"] >= 2 or
        counts["deployment"] >= 2 or
        counts["decision"] >= 3
    )
    current_fact = bool(live_score or (counts["factual"] and counts["freshness"]))
    needs_recent_context = bool(short_followup and hist) or context_dependency >= 3
    confidence_floor = 0.90 if verify_score >= 3 else (0.84 if evidence_score >= 3 else 0.78)

    top_categories=[k for k,_ in counts.most_common(8)]
    return {
        "version":"R11",
        "registry_signals":SIGNAL_COUNT,
        "matched_signal_count":len(matched),
        "matched_signals":matched[:80],
        "category_counts":dict(counts),
        "top_categories":top_categories,
        "route":{
            "tier":tier,
            "live_required":bool(live_score),
            "current_fact":current_fact,
            "prefer_smart_model":tier in {"smart","deep","apex"},
            "prefer_research_model":tier=="research",
        },
        "verification":{
            "second_pass":second_pass,
            "verify_score":verify_score,
            "confidence_floor":confidence_floor,
            "must_ground_current_claims":current_fact,
            "runtime_proof_for_completion":bool(counts["testing"] or counts["deployment"] or counts["debugging"]),
        },
        "context":{
            "short_followup":short_followup,
            "needs_recent_context":needs_recent_context,
            "context_dependency_score":context_dependency,
            "history_available":bool(hist),
            "project_context":bool(project_context),
        },
        "reasoning":{
            "hard_score":hard_score,
            "evidence_score":evidence_score,
            "uncertainty_score":uncertainty_score,
            "profile":profile,
        },
    }

def r11_route_hint(report: dict) -> str:
    return str((report.get("route") or {}).get("tier") or "fast")

def r11_directive(report: dict) -> str:
    route=report.get("route") or {}
    verify=report.get("verification") or {}
    context=report.get("context") or {}
    top=", ".join(report.get("top_categories") or []) or "general"
    rules=[
        "RONN R11 RELIABILITY CORE:",
        f"- Active registry: {report.get('registry_signals',600)} task/reliability signals; matched this request: {report.get('matched_signal_count',0)}.",
        f"- Dominant task signals: {top}.",
        f"- Recommended intelligence tier: {route.get('tier','fast')}.",
        "- Answer the user's actual intent, not merely the literal last sentence.",
        "- Separate known facts, inference, assumptions, and uncertainty. Never fill evidence gaps with confident guesses.",
        "- If the user corrects an earlier answer, re-evaluate from evidence instead of defending the previous answer.",
        "- Preserve explicit constraints and the newest instruction across follow-ups.",
    ]
    if context.get("needs_recent_context"):
        rules += [
            "- This appears context-dependent: resolve pronouns/short follow-ups from the recent conversation before asking the user to repeat information.",
            "- Prefer the most recent explicit user instruction when older context conflicts."
        ]
    if route.get("live_required"):
        rules += [
            "- This request is time-sensitive/research-dependent. Use live evidence when the route supports it; do not answer changing facts from stale memory as if current.",
            "- Prefer primary/official/recent sources and cross-check important claims."
        ]
    if verify.get("second_pass"):
        rules += [
            "- Perform an independent verification/critic pass before the final answer when provider capacity permits.",
            "- Repair contradictions, dropped requirements, unsupported specifics, and completion claims found by the verifier."
        ]
    if verify.get("runtime_proof_for_completion"):
        rules += [
            "- Do not say code/deployment is fixed, tested, live, or working unless runtime evidence actually supports that claim."
        ]
    return "\n".join(rules)

def r11_summary(report: dict) -> str:
    return json.dumps({
        "registry":report.get("registry_signals",600),
        "matched":report.get("matched_signal_count",0),
        "tier":(report.get("route") or {}).get("tier"),
        "verify":(report.get("verification") or {}).get("second_pass"),
        "context":(report.get("context") or {}).get("needs_recent_context"),
        "top":report.get("top_categories",[])[:5],
    }, ensure_ascii=False)
