from __future__ import annotations

import re
from typing import Any

R23_VERSION = "R23-BRAIN-1"

# Terms RONN should understand without wasting a web request.
_COMMON_SHORT = {
    "rmb","remember","rq","quick","real","rn","right","now","idk","imo","imho","btw",
    "fr","ngl","lol","lmao","brb","afk","tbh","wym","wdym","yk","yeah","yup","bro",
    "api","ui","ux","pc","cpu","gpu","ram","ssd","http","https","json","html","css",
    "js","ts","py","sql","ai","llm","gpt","url","app","web","ios","android"
}
_COMMON_WORDS = {
    "what","does","mean","who","is","are","how","why","when","where","which","can",
    "could","would","should","the","a","an","this","that","these","those","with","from",
    "about","for","and","or","but","not","my","your","our","their","his","her","its",
    "fix","help","make","build","create","tell","explain","use","work","works","working",
    "code","error","game","website","model","brain","search","find","look","latest","current"
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _tokens(text: str):
    return re.findall(r"[A-Za-z0-9_+.#-]{2,48}", str(text or ""))


def unknown_candidates(message: str) -> list[str]:
    """Detect terms that are worth resolving through retrieval before answering.

    This is deliberately conservative: it catches explicit meaning/identity requests,
    error/package identifiers, quoted terms, acronyms and unusual compact tokens while
    avoiding common slang RONN already knows.
    """
    raw = str(message or "")
    low = _norm(raw)
    found: list[str] = []

    def add(value: str):
        v = value.strip(" \'\".,!?;:()[]{}")
        if not v or len(v) < 2 or len(v) > 64:
            return
        vl = v.lower()
        if vl in _COMMON_SHORT or vl in _COMMON_WORDS:
            return
        if v not in found:
            found.append(v)

    # Explicit "what does X mean" / "what is X" for compact or quoted terms.
    for pat in (
        r"(?i)\bwhat\s+does\s+[\'\"]?([A-Za-z0-9_+.#-]{2,40})[\'\"]?\s+mean\b",
        r"(?i)\bmeaning\s+of\s+[\'\"]?([A-Za-z0-9_+.#-]{2,40})",
        r"(?i)\bwhat\s+is\s+[\'\"]([A-Za-z0-9_+.# -]{2,48})[\'\"]",
        r"(?i)\bwho\s+is\s+[\'\"]([A-Za-z0-9_+.# -]{2,48})[\'\"]",
    ):
        m = re.search(pat, raw)
        if m:
            add(m.group(1))

    # Quoted unfamiliar tokens often name products, APIs, slang, packages, etc.
    for q in re.findall(r"[\'\"]([^\'\"]{2,48})[\'\"]", raw):
        if len(q.split()) <= 4:
            add(q)

    # Technical identifiers and error codes are high-value retrieval targets.
    for tok in _tokens(raw):
        # A trailing sentence period must not turn an ordinary word into an
        # "unknown technical identifier". Internal dots still count (numpy.linalg,
        # v2.1, package.name, etc.).
        core = tok.strip(".")
        tl = core.lower()
        if not core or tl in _COMMON_SHORT or tl in _COMMON_WORDS:
            continue
        unusual = (
            bool(re.search(r"\d", core) and re.search(r"[A-Za-z]", core))
            or "_" in core or "." in core or "+" in core or "#" in core
            or (core.isupper() and 2 <= len(core) <= 12)
        )
        if unusual and not re.fullmatch(r"\d+(?:\.\d+)?", core):
            add(core)

    # Explicit uncertainty language should force retrieval even when the term is natural.
    if any(x in low for x in (
        "never heard of","dont know what","don't know what","unknown term",
        "unknown error","what is this error","what does this error","slang for"
    )):
        for tok in _tokens(raw):
            if tok.lower() not in _COMMON_WORDS and tok.lower() not in _COMMON_SHORT:
                add(tok)

    return found[:6]


def retrieval_reason(message: str, *, profile: str="", has_files: bool=False) -> dict[str, Any]:
    low = _norm(message)
    candidates = unknown_candidates(message)
    p=str(profile or "").strip().lower()

    explicit = any(x in low for x in (
        "search the web","look this up","look it up","find out","find sources",
        "research this","check online","search online"
    ))

    # Natural-language lookup intent. This intentionally looks for the meaning
    # of "go check/find this for me", not one exact command phrase.
    lookup_patterns=(
        r"\bcheck (?:that|this|it|those|these) out\b",
        r"\bcheck (?:that|this|it|those|these) (?:for me|online)\b",
        r"\b(?:can you |could you )?(?:find|look up|look into|check for|see if)\b",
        r"\bfind me\b",
        r"\bwhere (?:can|could) i (?:buy|get|find)\b",
        r"\bwhat(?:'s| is) new with\b",
    )
    natural_lookup=any(re.search(pat,low,re.I) for pat in lookup_patterns)

    freshness_patterns=(
        r"\b(?:latest|newest|current|currently|today|tonight|this week|recent|recently|breaking)\b",
        r"\b(?:new release|new drop|just dropped|dropping|restock|restocked|restocking|in stock|sold out|available now)\b",
        r"\b(?:release date|current version|price today|stock price|open now)\b",
        r"\b(?:score|standings|schedule|forecast|weather|news)\b",
    )
    current=any(re.search(pat,low,re.I) for pat in freshness_patterns)

    # "new" by itself is ambiguous. Treat it as fresh information only when the
    # user is clearly asking to inspect/find/check a real-world thing, not while
    # writing/creating or checking supplied code/files.
    new_lookup=bool(
        re.search(r"\bnew\b",low)
        and natural_lookup
        and p not in {"creative","writing","coding"}
        and not has_files
    )

    local = any(x in low for x in (
        "near me","nearby","closest","around me","in my area","my location","where am i",
        "restaurants near","food near","coffee near","open near me"
    ))

    required=bool(explicit or natural_lookup or current or new_lookup or local or candidates)
    reason=(
        "unknown_term" if candidates else
        "local" if local else
        "current" if (current or new_lookup) else
        "lookup" if natural_lookup else
        "explicit" if explicit else ""
    )
    return {
        "required": required,
        "explicit": explicit,
        "lookup": natural_lookup,
        "current": bool(current or new_lookup),
        "local": local,
        "unknown_terms": candidates,
        "reason": reason,
    }


def capability_plan(base: dict, message: str, *, history=None, file_names=None,
                    has_images=False, has_project=False, agent_mode=True) -> dict:
    history = history or []
    file_names = file_names or []
    low = _norm(message)
    difficulty = int(base.get("difficulty") or 1)
    retrieval = retrieval_reason(
        message,
        profile=str(base.get("profile") or ""),
        has_files=bool(file_names),
    )

    coding = str(base.get("profile") or "") == "coding"
    has_url = bool(re.search(r"https?://[^\s]+", str(message or ""), re.I))
    execution_words = any(x in low for x in (
        "run this","execute this","test this","test the code","debug this","fix this",
        "repair this","run tests","test and fix","fix and test","retest"
    ))
    research_words = any(x in low for x in (
        "research","investigate","compare sources","deep dive","find evidence","sources"
    ))
    world_words = any(x in low for x in (
        "architecture","dependency","dependencies","impact","simulate","simulation",
        "what will break","before changing","whole project","entire project","system design"
    ))
    browser_words = any(x in low for x in (
        "open the website","click","type into","fill out","fill in","browser agent",
        "navigate to","use the browser","on this website","press the button","select the",
        "choose the","open this site"
    ))
    computer_words = any(x in low for x in (
        "use my computer","control my computer","my desktop","my screen","connected computer",
        "computer agent"
    ))
    # Browser Use is intentionally scoped to an explicit R23-approved URL.
    # Open-ended discovery stays on the existing research pipeline.
    browser_interactive = bool(browser_words and has_url)

    return {
        "strong_main_brain": True,
        "agent_runtime": bool(agent_mode and (retrieval["required"] or file_names or has_url or browser_interactive or computer_words or execution_words)),
        "browser_url": bool(has_url),
        "browser_interactive": browser_interactive,
        "code_fix_loop": bool(coding and file_names and execution_words),
        "project_brain": bool(has_project or file_names or base.get("followup") or len(history) >= 6),
        "long_context": bool(len(history) >= 12 or base.get("followup") or has_project),
        "evaluation_lab": True,
        "model_competition": bool(difficulty >= 6 and not retrieval["required"] and not has_images),
        "world_model": bool((len(file_names) >= 2 and (coding or world_words)) or (has_project and world_words)),
        "failure_learning": True,
        "autonomous_research": bool(retrieval["required"] and (research_words or difficulty >= 4 or retrieval["unknown_terms"])),
        "universal_retrieval": bool(retrieval["required"]),
        "computer_requested": bool(computer_words),
        "retrieval": retrieval,
    }


def status() -> dict[str, Any]:
    return {
        "version": R23_VERSION,
        "feature_count": 11,
        "features": {
            "1_stronger_main_brain": True,
            "2_full_agent_runtime": True,
            "3_code_test_fix_retest": True,
            "4_permanent_project_brain": True,
            "5_long_context_compression": True,
            "6_real_evaluation_lab": True,
            "7_automatic_model_competition": True,
            "8_world_model_simulation": True,
            "9_failure_learning": True,
            "10_autonomous_research": True,
            "11_universal_retrieval": True,
        },
        "architecture": "one main brain + capability plane",
    }
