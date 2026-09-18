
def task_difficulty(message: str) -> int:
    low = (message or "").lower()
    score = 0
    if len(low) > 500: score += 1
    if len(low) > 1600: score += 1
    for x in (
        "architecture","full game","complete system","whole system","analyze","research","debug",
        "implement","multi-file","production","optimize","complex","hard","entire","from scratch"
    ):
        if x in low:
            score += 1
    if any(x in low for x in ("multi-agent","multiple files","large project","deep research","prove","verify everything","long horizon")):
        score += 2
    return min(score, 8)

def infer_intent(message: str):
    low = (message or "").lower()
    if any(x in low for x in ("website","frontend","html","css","javascript","typescript","react")):
        return "frontend"
    if any(x in low for x in ("error","broken","failed","not working","busy","429","timeout")):
        return "debug"
    if any(x in low for x in ("latest","today","current","news","research","source","weather","look up")):
        return "research"
    if any(x in low for x in ("calculate","equation","algebra","geometry","physics","chemistry","math")):
        return "mathscience"
    if any(x in low for x in ("write","rewrite","essay","summary","paragraph")):
        return "writing"
    return "general"

def intelligence_directive(message: str, difficulty: int, intent: str):
    rules = [
        "Infer the user's real intent even when wording is short, slangy, misspelled, or informal.",
        "Use conversation, project, file, memory, and tool context instead of asking for details already available.",
        "Do not claim an action, search, calculation, or test happened unless an actual tool/provider result confirms it.",
        "Prefer a complete useful result over generic instructions when RONN has the capability to do the work.",
    ]
    if difficulty >= 3:
        rules += [
            "Internally separate requirements, architecture, implementation, and verification.",
            "Check dependencies, names, interfaces, edge cases, and failure paths before finalizing.",
        ]
    if difficulty >= 5:
        rules += [
            "Compare multiple plausible solution approaches internally and choose the more robust one.",
            "Perform a final contradiction and consistency review.",
        ]
    if intent in {"debug","frontend","general"} and difficulty >= 4:
        rules += [
            "Use counterexamples and an independent verification pass before finalizing high-impact conclusions.",
        ]
    if intent in {"research","mathscience"}:
        rules += [
            "Use live/tool-enabled routes when freshness or calculation accuracy matters.",
        ]
    return "RONN SMART INTELLIGENCE SYSTEM:\n- " + "\n- ".join(rules)
