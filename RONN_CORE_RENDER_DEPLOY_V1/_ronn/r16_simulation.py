"""RONN R16 project world-model and change simulation."""
from __future__ import annotations
import difflib, re
from pathlib import PurePosixPath

IMPORT_PATTERNS=[
    re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",re.M),
    re.compile(r"""(?:require\(|from\s+|import\s+)["']([^"']+)["']"""),
]

def _item(f):
    if isinstance(f,dict):
        return str(f.get("name","file")),str(f.get("content",""))
    return str(getattr(f,"name","file")),str(getattr(f,"content",""))

def _resolve(name,dep,names):
    dep=dep.lstrip("./").replace(".","/")
    candidates=[dep,dep+".py",dep+".js",dep+".ts",dep+"/index.js",dep+"/index.ts"]
    base=str(PurePosixPath(name).parent)
    if base!=".":
        candidates += [base+"/"+x for x in candidates]
    low={n.lower():n for n in names}
    for c in candidates:
        if c.lower() in low:return low[c.lower()]
    stem=dep.split("/")[-1].lower()
    for n in names:
        if PurePosixPath(n).stem.lower()==stem:return n
    return None

def project_model(files):
    items=[_item(f) for f in list(files or [])[:80]]
    names=[n for n,_ in items]
    edges=[]
    for name,content in items:
        deps=[]
        for pat in IMPORT_PATTERNS:
            for m in pat.finditer(content[:60000]):
                val=next((g for g in m.groups() if g),None)
                if val and val not in deps:deps.append(val)
        for dep in deps[:30]:
            target=_resolve(name,dep,names)
            if target and target!=name:
                edges.append({"from":name,"to":target,"relation":"imports"})
    incoming={n:0 for n in names}
    for e in edges:incoming[e["to"]]=incoming.get(e["to"],0)+1
    hubs=sorted(incoming,key=lambda n:incoming[n],reverse=True)[:10]
    return {"nodes":names,"edges":edges,"hubs":[{"file":n,"incoming":incoming[n]} for n in hubs if incoming[n]>0]}

def simulate(before_files,after_files):
    before=dict(_item(f) for f in list(before_files or []))
    after=dict(_item(f) for f in list(after_files or []))
    all_names=sorted(set(before)|set(after))
    changes=[]; score=0
    world=project_model([{"name":n,"content":after.get(n,before.get(n,""))} for n in all_names])
    hub={x["file"]:x["incoming"] for x in world["hubs"]}
    for n in all_names:
        a=before.get(n); b=after.get(n)
        if a==b:continue
        if a is None:kind="added"
        elif b is None:kind="deleted"
        else:kind="modified"
        ratio=0.0 if a is None or b is None else difflib.SequenceMatcher(None,a[:40000],b[:40000]).ratio()
        changed=int((1-ratio)*max(len(a or ""),len(b or "")))
        local=1+(3 if kind=="deleted" else 0)+(2 if hub.get(n,0)>=2 else 0)+(2 if changed>6000 else 0)
        score+=local
        changes.append({"file":n,"kind":kind,"approx_changed_chars":changed,"dependency_weight":hub.get(n,0),"risk":min(10,local)})
    level="low" if score<=3 else ("medium" if score<=9 else "high")
    return {"risk_score":min(100,score*7),"risk_level":level,"changes":changes,"world_model":world,
            "recommendation":"Test in a shadow workspace before applying." if changes else "No changes detected."}
