
from pathlib import Path

BASE = Path(__file__).resolve().parent
SKILLS_DIR = BASE / "skills"

SKILL_KEYWORDS = {
    "software_engineer.md": ("code","coding","python","javascript","typescript","api","backend","frontend","script","website","app","database","sql","refactor"),
    "debugger.md": ("error","broken","doesn't work","doesnt work","not working","failed","crash","bug","issue","429","401","500","offline","timeout"),
    "architecture_reviewer.md": ("architecture","multi-file","whole system","entire system","full project","module","dependency","scalable"),
    "test_engineer.md": ("test","testing","verify","bug fix","regression","quality","validate"),
    "game_designer.md": ("game idea","game design","gameplay loop","progression","map concept","boss","quest","inventory","level design"),
    "frontend_designer.md": ("website","frontend","landing page","ui","ux","dashboard","responsive","html","css"),
    "researcher.md": ("latest","today","current","research","sources","compare","news","price","weather","look up"),
    "deep_reasoner.md": ("hard","complex","analyze","analysis","architecture","plan","strategy","math","science","why","tradeoff","optimize"),
    "writer.md": ("write","rewrite","essay","paragraph","summary","summarize","email","message","explain"),
    "tool_planner.md": ("do it","create it","make it for me","tool","agent","workflow","automate"),
    "fact_checker.md": ("fact","verify","true","source","evidence","claim","accurate","latest","research"),
    "causal_analyst.md": ("cause","causal","why","effect","correlation","intervention","confound"),
    "adversarial_reviewer.md": ("review","critic","challenge","counterexample","risk","weakness","prove wrong"),
    "data_analyst.md": ("data","dataset","csv","spreadsheet","statistics","chart","average","trend"),
    "document_analyst.md": ("pdf","document","docx","xlsx","pptx","file","report","paper"),
    "strategy_planner.md": ("plan","roadmap","milestone","project","strategy","long term","steps"),
    "outcome_evaluator.md": ("verify","complete","done","finished","acceptance","outcome","requirements"),
    "security_reviewer.md": ("security","auth","secret","credential","permission","injection","token"),
}

def _read(name):
    try:
        return (SKILLS_DIR / name).read_text(encoding="utf-8")
    except Exception:
        return ""

def choose_skills(message: str, profile: str = "", max_skills: int = 5):
    low = (message or "").lower()
    scored = []
    for name, keys in SKILL_KEYWORDS.items():
        score = sum(2 if " " in k else 1 for k in keys if k in low)
        if profile == "coding" and name == "software_engineer.md":
            score += 8
        if profile == "creative" and name == "game_designer.md":
            score += 7
        if profile in {"analysis","knowledge"} and name == "fact_checker.md":
            score += 5
        if profile == "research" and name == "fact_checker.md":
            score += 6
        if profile == "research" and name == "researcher.md":
            score += 8
        if score:
            scored.append((score, name))
    scored.sort(reverse=True)
    names = [name for _, name in scored[:max_skills]]

    hard_words = ("build","create","implement","fix","hard","complex","entire","complete","whole system")
    if any(x in low for x in hard_words):
        for extra in ("deep_reasoner.md","architecture_reviewer.md","test_engineer.md","tool_planner.md"):
            if extra not in names and len(names) < max_skills:
                names.append(extra)
    return names

def build_skill_context(message: str, profile: str = ""):
    names = choose_skills(message, profile)
    blocks = [_read(n).strip() for n in names]
    blocks = [b for b in blocks if b]
    return "\n\n".join(blocks)[:15000], names
