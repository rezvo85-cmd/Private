"""RONN R15 evaluation lab for major capability regressions."""
from __future__ import annotations
import time
from r14_benchmarks import run_r14_benchmarks
from r14_sandbox import execute as safe_python
from r14_tool_brain import plan as tool_plan
from r16_simulation import project_model
from r17_browser import normalize_url
from r19_context import conversation_digest, evidence_plan

def _case(name,fn):
    t=time.time()
    try:
        ok=bool(fn())
        return {"name":name,"passed":ok,"ms":round((time.time()-t)*1000,2),"error":"" if ok else "condition failed"}
    except Exception as exc:
        return {"name":name,"passed":False,"ms":round((time.time()-t)*1000,2),"error":str(exc)[:200]}

def run():
    base=run_r14_benchmarks()
    tests=[
      _case("safe execution still works",lambda:safe_python("print(6*7)")["output"].strip()=="42"),
      _case("tool brain routes live facts",lambda:any(x["tool"]=="live_research" for x in tool_plan("latest AI news",current=True)["tools"])),
      _case("project world model finds dependency",lambda:"b.py" in project_model([{"name":"a.py","content":"import b"},{"name":"b.py","content":"x=1"}])["nodes"]),
      _case("browser URL normalizer accepts https",lambda:normalize_url("https://example.com")=="https://example.com"),
      _case("long context creates digest",lambda:len(conversation_digest([{"role":"user","content":"Keep the API name stable"}]*30))>0),
      _case("evidence planner flags current",lambda:"live_research" in evidence_plan("what is the latest version",False,False)["sources"]),
    ]
    passed=sum(1 for x in tests if x["passed"])
    return {"passed":passed,"total":len(tests),"score":round(100*passed/max(1,len(tests)),1),"tests":tests,"r14":base}
