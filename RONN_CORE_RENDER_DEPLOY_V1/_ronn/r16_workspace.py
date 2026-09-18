"""RONN R16 controlled execution workspace.

This is intentionally narrower than unrestricted shell access. It gives RONN
real syntax/runtime verification for Python and JavaScript while stripping
secrets, constraining paths, time, output and process resources.
"""
from __future__ import annotations
import ast, json, os, re, shutil, subprocess, time, uuid
from pathlib import Path
from r15_trust import checkpoint, mark_rolled_back, rollback_payload
from r16_runner import status as runner_status, execute as runner_execute

BASE=Path(__file__).resolve().parent
ROOT=BASE/"data"/"workspaces"
ROOT.mkdir(parents=True,exist_ok=True)
MAX_FILE=600000
MAX_OUTPUT=30000

def _slug(x):
    return re.sub(r"[^A-Za-z0-9_-]","_",str(x or "default"))[:80] or "default"

def root(owner,workspace="default"):
    p=ROOT/_slug(owner)/_slug(workspace)
    p.mkdir(parents=True,exist_ok=True)
    return p

def _path(owner,workspace,name):
    base=root(owner,workspace).resolve()
    rel=Path(str(name or "file.txt").replace("\\","/"))
    if rel.is_absolute() or ".." in rel.parts:raise ValueError("Unsafe workspace path.")
    p=(base/rel).resolve()
    if base not in p.parents and p!=base:raise ValueError("Unsafe workspace path.")
    p.parent.mkdir(parents=True,exist_ok=True)
    return p

def write(owner,workspace,name,content):
    p=_path(owner,workspace,name)
    text=str(content or "")
    if len(text.encode("utf-8"))>MAX_FILE:raise ValueError("File exceeds workspace limit.")
    before=p.read_text("utf-8",errors="replace") if p.exists() else None
    p.write_text(text,encoding="utf-8")
    action=checkpoint(owner,"workspace_write",f"{workspace}/{name}",
                      before={"content":before,"exists":before is not None},
                      after={"content":text,"exists":True},risk="low",reversible=True,
                      evidence={"bytes":len(text.encode("utf-8"))})
    return {"ok":True,"file":str(name),"bytes":len(text.encode("utf-8")),"action_id":action["id"]}

def read(owner,workspace,name):
    p=_path(owner,workspace,name)
    if not p.exists() or not p.is_file():raise FileNotFoundError(name)
    return {"file":str(name),"content":p.read_text("utf-8",errors="replace")[:MAX_FILE]}

def list_files(owner,workspace="default"):
    base=root(owner,workspace)
    out=[]
    for p in base.rglob("*"):
        if p.is_file():
            out.append({"name":p.relative_to(base).as_posix(),"bytes":p.stat().st_size})
        if len(out)>=200:break
    return out

def _clean_env():
    keep=("PATH","HOME","LANG","LC_ALL","TMPDIR","SYSTEMROOT","WINDIR")
    env={k:v for k,v in os.environ.items() if k in keep}
    env.update({"PYTHONNOUSERSITE":"1","RONN_SANDBOX":"1"})
    return env

def _limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(6,6))
        resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
        resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024*1024,4*1024*1024))
        resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    except Exception:
        pass

PY_SAFE_IMPORTS={"math","statistics","json","re","collections","itertools","functools","decimal","fractions"}
PY_BLOCKED_NAMES={"open","exec","eval","compile","__import__","input","globals","locals","vars","getattr","setattr","delattr","breakpoint","help","dir"}
JS_BAD=("child_process","process.env","require('fs')",'require("fs")',"fetch(","XMLHttpRequest","WebSocket(")

def _validate_python(text):
    tree=ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n,(ast.Import,ast.ImportFrom)):
            names=[x.name.split(".")[0] for x in n.names] if isinstance(n,ast.Import) else [(n.module or "").split(".")[0]]
            if any(x not in PY_SAFE_IMPORTS for x in names):
                raise ValueError("The local runner only permits safe standard-library imports.")
        if isinstance(n,ast.Name) and (n.id.startswith("__") or n.id in PY_BLOCKED_NAMES):
            raise ValueError(f"Blocked name in local runner: {n.id}")
        if isinstance(n,ast.Attribute) and n.attr.startswith("_"):
            raise ValueError("Private/dunder attributes are blocked in the local runner.")
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in PY_BLOCKED_NAMES:
            raise ValueError(f"Blocked call in local runner: {n.func.id}")

def _validate_js(text):
    low=text.lower()
    if any(x.lower() in low for x in JS_BAD):raise ValueError("This local runner blocks filesystem, process-secret and network access.")

def run(owner,workspace,entry,language="auto",execute=True):
    p=_path(owner,workspace,entry)
    if not p.exists():raise FileNotFoundError(entry)
    text=p.read_text("utf-8",errors="replace")
    ext=p.suffix.lower()
    lang=("python" if ext==".py" else "javascript" if ext in {".js",".mjs",".cjs"} else language).lower()
    remote=runner_status()
    if execute and remote.get("verified"):
        base=root(owner,workspace)
        files=[]
        for fp in base.rglob("*"):
            if fp.is_file() and fp.stat().st_size<=MAX_FILE:
                files.append({"name":fp.relative_to(base).as_posix(),"content":fp.read_text("utf-8",errors="replace")})
            if len(files)>=60:break
        result=runner_execute(files,str(Path(entry).as_posix()),lang,30)
        result["runtime"]="isolated-full-runner"
        return result
    if lang=="python":
        _validate_python(text)
        cmd=[shutil.which("python") or shutil.which("python3") or "python","-m","py_compile",str(p)] if not execute else [shutil.which("python") or shutil.which("python3") or "python",str(p)]
    elif lang in {"javascript","js"}:
        _validate_js(text)
        node=shutil.which("node")
        if not node:return {"ok":False,"verified":False,"error":"Node.js is not installed in this runtime.","language":"javascript"}
        # Local JS is syntax-verified only. Full JS execution belongs in the isolated runner service.
        cmd=[node,"--check",str(p)]
        execute=False
    else:
        raise ValueError("Only Python and JavaScript are executable in the local safe runner.")
    started=time.time()
    try:
        cp=subprocess.run(cmd,cwd=str(root(owner,workspace)),env=_clean_env(),capture_output=True,text=True,
                          timeout=10,preexec_fn=_limits if os.name!="nt" else None)
        out=(cp.stdout or "")[-MAX_OUTPUT:]; err=(cp.stderr or "")[-MAX_OUTPUT:]
        ok=cp.returncode==0
        return {"ok":ok,"verified":True,"returncode":cp.returncode,"stdout":out,"stderr":err,
                "language":lang,"execute":bool(execute),"ms":round((time.time()-started)*1000,2)}
    except subprocess.TimeoutExpired:
        return {"ok":False,"verified":True,"error":"Execution timed out.","language":lang,"execute":bool(execute)}

def rollback(owner,action_id,workspace,name):
    rb=rollback_payload(action_id)
    if not rb.get("ok"):return rb
    action=rb["action"]
    if action.get("owner")!=str(owner):return {"ok":False,"reason":"owner_mismatch"}
    state=rb.get("restore") or {}
    p=_path(owner,workspace,name)
    if state.get("exists"):
        p.write_text(str(state.get("content") or ""),encoding="utf-8")
    elif p.exists():
        p.unlink()
    mark_rolled_back(action_id,{"restored":str(name),"at":int(time.time())})
    return {"ok":True,"restored":str(name),"action_id":action_id}

def status():
    return {"workspace_root":str(ROOT),"python":bool(shutil.which("python") or shutil.which("python3")),
            "node":bool(shutil.which("node")),"mode":"controlled-local-execution","network_allowed":False,"javascript_local_mode":"syntax-check-only",
            "full_runner":runner_status()}
