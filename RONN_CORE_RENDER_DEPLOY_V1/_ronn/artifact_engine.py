import json, ast, csv, io, re, hashlib, time
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE/"workspaces"
ROOT.mkdir(parents=True,exist_ok=True)

def _safe_name(s,default="workspace"):
    s=re.sub(r"[^A-Za-z0-9._ -]","_",str(s or "")).strip(" .")
    return (s[:80] or default)

def workspace(name="default"):
    p=ROOT/_safe_name(name)
    p.mkdir(parents=True,exist_ok=True)
    return p

def write_artifact(space, filename, content):
    root=workspace(space).resolve()
    name=_safe_name(filename,"artifact.txt")
    p=(root/name).resolve()
    if p.parent!=root:
        raise ValueError("Invalid artifact path.")
    p.write_text(str(content or ""),encoding="utf-8")
    return {"name":p.name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}

def list_artifacts(space="default"):
    root=workspace(space)
    return [{"name":p.name,"bytes":p.stat().st_size,"modified":p.stat().st_mtime}
            for p in sorted(root.iterdir()) if p.is_file()][:200]

def inspect_text(language, text):
    language=(language or "").lower()
    issues=[]
    meta={"chars":len(text or ""),"lines":len((text or "").splitlines())}
    if language in ("python","py"):
        try:
            tree=ast.parse(text or "")
            meta["functions"]=sum(isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) for x in ast.walk(tree))
            meta["classes"]=sum(isinstance(x,ast.ClassDef) for x in ast.walk(tree))
        except SyntaxError as e:
            issues.append(f"Python syntax line {e.lineno}: {e.msg}")
    elif language=="json":
        try:
            obj=json.loads(text or "")
            meta["root_type"]=type(obj).__name__
        except Exception as e:
            issues.append(f"JSON: {e}")
    elif language=="csv":
        try:
            rows=list(csv.reader(io.StringIO(text or "")))
            meta["rows"]=len(rows); meta["columns"]=max([len(r) for r in rows],default=0)
        except Exception as e:
            issues.append(f"CSV: {e}")
    elif language in ("javascript","js","typescript","ts"):
        if (text or "").count("{")!=(text or "").count("}"): issues.append("Brace count mismatch")
        if (text or "").count("(")!=(text or "").count(")"): issues.append("Parenthesis count mismatch")
    return {"passed":not issues,"issues":issues,"meta":meta,"scope":"safe_static_lab"}

def compare_candidates(candidates):
    # Deterministic structural comparison only, not semantic correctness.
    out=[]
    for i,c in enumerate(candidates or []):
        text=str(c.get("text",""))
        score=0
        if text.strip(): score+=1
        if len(text)>100: score+=1
        if "TODO" not in text and "PLACEHOLDER" not in text: score+=1
        if text.count("```")%2==0: score+=1
        out.append({"index":i,"structural_score":score,"chars":len(text)})
    return sorted(out,key=lambda x:(-x["structural_score"],-x["chars"]))
