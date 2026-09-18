
import ast
import json
import math
import difflib
import re

TOOL_CATALOG = {
    "groq_web_search": "Live web search through Groq Compound for current information.",
    "groq_visit_website": "Reads and analyzes public webpages through Groq Compound.",
    "groq_code_interpreter": "Runs Python in Groq's hosted sandbox for calculations and code-based analysis.",
    "groq_wolfram": "Computational knowledge/math through Groq Compound when available.",
    "vision": "Understands attached images/screenshots.",
    "document_intelligence": "Extracts text from PDF, DOCX, XLSX and PPTX files locally for analysis.",
    "project_memory": "Retrieves relevant saved project/user memories.",
    "project_brain": "Retrieves persistent decisions, constraints, failures and dependency relationships.",
    "context_compiler": "Selects the highest-value context for the current task instead of dumping everything into one prompt.",
    "experience_engine": "Tracks task routes, latency and explicit user feedback for measured routing improvements.",
    "evaluation_suite": "Runs deterministic regression tests over RONN's local intelligence architecture.",
    "artifact_workspace": "Creates and inspects text/code artifacts inside RONN's own safe workspace without shell access.",
    "local_calculator": "Safe deterministic arithmetic without shell execution.",
    "json_validator": "Validates and formats JSON.",
    "text_diff": "Creates unified text diffs.",
    "code_sanity": "Light static sanity checks for generated code."
}

_ALLOWED_AST = (
    ast.Expression, ast.Constant, ast.BinOp, ast.UnaryOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Load,
)

def safe_calculate(expression: str):
    expression = (expression or "").strip()
    if len(expression) > 300:
        raise ValueError("Expression is too long.")
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST):
            raise ValueError("Only arithmetic expressions are allowed.")
    value = eval(compile(tree, "<ronn-calc>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("Result is not a finite number.")
    return value

def validate_json(text: str):
    obj = json.loads(text)
    return json.dumps(obj, indent=2, ensure_ascii=False)

def unified_diff(old: str, new: str, old_name="before", new_name="after"):
    return "\n".join(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(),
        fromfile=old_name, tofile=new_name, lineterm=""
    ))

def code_sanity(language: str, code: str):
    issues = []
    low = (language or "").lower()
    if low in {"python","py"}:
        try:
            ast.parse(code)
        except SyntaxError as exc:
            issues.append(f"Python syntax: line {exc.lineno}: {exc.msg}")
    elif low in {"lua","luau"}:
        # Lightweight structural heuristics only; this is not a full Luau parser.
        opens = len(re.findall(r"\b(function|if|for|while|repeat|do)\b", code))
        ends = len(re.findall(r"\bend\b", code))
        if ends == 0 and opens > 2:
            issues.append("Luau sanity: code has multiple block openings but no 'end' tokens.")
        if "RemoteEvent" in code and "OnServerEvent" in code and "typeof(" not in code:
            issues.append("Roblox networking: server RemoteEvent handler may need argument validation.")
    elif low in {"javascript","js","typescript","ts"}:
        if code.count("{") != code.count("}"):
            issues.append("JS/TS sanity: brace count does not match.")
        if code.count("(") != code.count(")"):
            issues.append("JS/TS sanity: parenthesis count does not match.")
    return issues
