import re
from collections import Counter

HARD_WORDS = (
    "build","create","design","architecture","debug","fix","analyze","whole","complete",
    "system","project","production","optimize","refactor","integrate","roblox","studio",
    "research","compare","plan","complex","advanced","game"
)

def cognitive_profile(message: str, difficulty: int, intent: str, profile: str):
    low = (message or "").lower()
    verification = difficulty >= 3 or any(x in low for x in ("debug","fix","production","complete","whole system"))
    alternatives = difficulty >= 4 or any(x in low for x in ("best way","architecture","design","compare"))
    decomposition = difficulty >= 2 or len(message or "") > 260
    return {
        "intent": intent,
        "profile": profile,
        "difficulty": difficulty,
        "decomposition": decomposition,
        "alternatives": alternatives,
        "verification": verification,
        "constraint_tracking": difficulty >= 2,
        "failure_analysis": any(x in low for x in ("error","broken","doesn't work","doesnt work","bug","failed","crash")),
        "research_awareness": any(x in low for x in ("latest","today","current","newest","research","source")),
    }

def cognition_directive(state: dict):
    rules = [
        "COGNITIVE CONTROL:",
        "- Infer the user's real goal from wording, conversation, files, memory, and active project context.",
        "- Never expose hidden chain-of-thought. Return conclusions, checks, decisions, and useful summaries only.",
        "- Track explicit requirements and do not silently drop constraints.",
        "- If a tool is required to know something, use the tool route instead of pretending.",
    ]
    if state.get("decomposition"):
        rules.append("- Privately decompose the task into dependent subproblems before producing the result.")
    if state.get("alternatives"):
        rules.append("- Privately compare multiple viable approaches and choose the one with the best correctness, maintainability, and fit.")
    if state.get("failure_analysis"):
        rules.append("- For failures, identify the root cause and affected dependency chain before changing code.")
    if state.get("verification"):
        rules += [
            "- Run a final consistency pass: requirements, interfaces, names, dependencies, edge cases, and likely failure modes.",
            "- Do not say something is tested, executed, applied, searched, or verified unless a real tool/result supports that claim.",
        ]
    return "\n".join(rules)

def extract_project_graph(project_context: str, files, snapshot=None):
    text = (project_context or "") + "\n"
    for f in files or []:
        text += f"\n{getattr(f,'name','file')} {getattr(f,'content','')[:12000]}"
    nodes = []
    edges = []
    seen = set()

    patterns = [
        ("Remote", r"\b([A-Za-z_][A-Za-z0-9_]*(?:Remote|Event|Function))\b"),
        ("Module", r"\b([A-Za-z_][A-Za-z0-9_]*(?:Service|Controller|Manager|Module|Handler|Config))\b"),
        ("Script", r"\b([A-Za-z_][A-Za-z0-9_]*(?:Script|Client|Server))\b"),
    ]
    for kind, pat in patterns:
        for name in re.findall(pat, text):
            key=(kind,name)
            if key not in seen:
                seen.add(key); nodes.append({"type":kind,"name":name})
            if len(nodes) >= 80: break

    # Lightweight dependency hints from require() and common service references.
    reqs = re.findall(r'require\s*\(\s*[^)]*?([A-Za-z_][A-Za-z0-9_]*)\s*\)', text)
    for name in reqs[:40]:
        edges.append({"relation":"requires","target":name})

    if isinstance(snapshot, dict):
        for service in snapshot.get("services", [])[:20] if isinstance(snapshot.get("services"), list) else []:
            if isinstance(service, dict) and service.get("name"):
                nodes.append({"type":"Studio","name":str(service["name"])[:100]})

    return {"nodes":nodes[:100], "edges":edges[:80], "node_count":len(nodes[:100])}

def task_stages(state: dict):
    stages = ["Understand"]
    if state.get("decomposition"): stages.append("Plan")
    if state.get("research_awareness"): stages.append("Research")
    stages.append("Build")
    if state.get("verification"): stages += ["Check", "Verify"]
    return stages
