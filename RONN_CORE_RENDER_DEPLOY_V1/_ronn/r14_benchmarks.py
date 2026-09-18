"""Deterministic R14 capability regression checks."""
from __future__ import annotations
import time
from r14_sandbox import execute as sandbox_execute, SandboxError
from r14_tool_brain import plan as tool_plan
from r14_multimodal import plan as multimodal_plan
from r14_self_correct import inspect as self_inspect
from r14_agent import make_plan as agent_plan

def _case(name, fn):
    t=time.time()
    try:
        ok=bool(fn())
        return {"name":name,"passed":ok,"ms":round((time.time()-t)*1000,2),"error":"" if ok else "condition failed"}
    except Exception as exc:
        return {"name":name,"passed":False,"ms":round((time.time()-t)*1000,2),"error":str(exc)[:180]}

def _blocked_import():
    try:
        sandbox_execute("import os\nprint(os.getcwd())")
        return False
    except Exception:
        return True

def run_r14_benchmarks():
    tests=[
      _case("safe sandbox executes arithmetic",lambda: sandbox_execute("x=7*6\nprint(x)")["output"].strip()=="42"),
      _case("sandbox blocks imports",_blocked_import),
      _case("tool brain selects research",lambda:any(x["tool"]=="live_research" for x in tool_plan("what is the latest version",current=True)["tools"])),
      _case("tool brain selects code sandbox",lambda:any(x["tool"]=="safe_code_sandbox" for x in tool_plan("debug this python code","coding")["tools"])),
      _case("multimodal screenshot mode",lambda:multimodal_plan("look at this screenshot",1,[])["screenshot_mode"]),
      _case("self correction flags fake verification",lambda:self_inspect("fix this","I fixed and tested it.",False)["needs_repair"]),
      _case("agent creates verification step",lambda:any(x["step"]=="verify" for x in agent_plan("build and test this","coding")["steps"])),
    ]
    passed=sum(1 for t in tests if t["passed"])
    total=len(tests)
    return {"passed":passed,"total":total,"score":round((passed/total)*100 if total else 0,1),"tests":tests}
