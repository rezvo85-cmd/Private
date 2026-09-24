from __future__ import annotations

import json
import os
import py_compile
from pathlib import Path

from brevity_engine import response_length_policy, brevity_directive
from r20_tool_hub import plan as tool_plan

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent

def run():
    checks=[]
    def add(name,ok,detail=""):
        checks.append({"name":name,"passed":bool(ok),"detail":detail})

    try:
        p=response_length_policy("who's jolyne kujo","balanced",0,False,False,False)
        d=brevity_directive(p)
        add("short_answers",p.get("tier")=="quick" and int(p.get("max_tokens") or 999)<=180 and "Do not use headings, bullets" in d,p)
    except Exception as exc:
        add("short_answers",False,str(exc)[:240])

    try:
        tools=tool_plan("what's the weather in Seattle",needs_live=True)
        add("tool_hub_weather","weather" in tools,tools)
    except Exception as exc:
        add("tool_hub_weather",False,str(exc)[:240])

    try:
        appjs=(BASE/"static/app.js").read_text(encoding="utf-8")
        css=(BASE/"static/style.css").read_text(encoding="utf-8")
        server=(BASE/"app.py").read_text(encoding="utf-8")
        add("rich_answer_cards",all(x in appjs+css for x in ("renderMetaCards","weatherCard","sourceCards")),"weather + source presentation")
        add("tool_protocol_guard","looksInternalToolPayload" in appjs and "looks_like_internal_tool_payload" in server,"client + server guards")
    except Exception as exc:
        add("presentation_and_guard",False,str(exc)[:240])

    try:
        mobile=(ROOT/"mobile/App.js").read_text(encoding="utf-8")
        pkg=json.loads((ROOT/"mobile/package.json").read_text(encoding="utf-8"))
        cfg=json.loads((ROOT/"mobile/app.json").read_text(encoding="utf-8"))
        api_ok=('const API="https://ronn-core.onrender.com/api/v1"' in mobile and 'API+"/chat/complete"' in mobile)
        ok=all(x in mobile for x in ("KeyboardAvoidingView","TextInput","FlatList","X-RONN-OP-Session")) and api_ok and "expo-secure-store" in json.dumps(pkg) and cfg.get("expo",{}).get("ios",{}).get("bundleIdentifier")=="com.ronn.ai"
        add("native_mobile_shell",ok,"native input/scroll/auth shell")
    except Exception as exc:
        add("native_mobile_shell",False,str(exc)[:240])

    try:
        for name in ("core_store_pg.py","memory_store_pg.py","r20_tool_hub.py"):
            py_compile.compile(str(BASE/name),doraise=True)
        add("cloud_storage_adapters",True,"Postgres adapters compile; activation still depends on DATABASE_URL")
    except Exception as exc:
        add("cloud_storage_adapters",False,str(exc)[:240])

    try:
        blueprint=(ROOT.parent/"render.yaml").read_text(encoding="utf-8")
        binding_ok=all(x in blueprint for x in (
            "name: RONN_CORE",
            "key: DATABASE_URL",
            "fromDatabase:",
            "name: RONN_MEMORY",
            "property: connectionString",
        )) and "postgresql://" not in blueprint and "postgres://" not in blueprint and "password:" not in blueprint
        add(
            "database_blueprint_binding",
            binding_ok,
            "DATABASE_URL securely references RONN_MEMORY via Render fromDatabase",
        )
    except Exception as exc:
        add("database_blueprint_binding",False,str(exc)[:240])

    # On the actual Render service, the secure Blueprint declaration is not
    # enough by itself: the runtime must really have DATABASE_URL.
    database_url_configured=bool(os.getenv("DATABASE_URL","").strip())
    on_render=bool(os.getenv("RENDER","").strip() or os.getenv("RENDER_SERVICE_ID","").strip())
    if on_render:
        add(
            "database_runtime_binding",
            database_url_configured,
            "DATABASE_URL is configured in the running Render service" if database_url_configured
            else "DATABASE_URL is missing from the running Render service",
        )

    # Production should have the two runtime helpers available, while DeepEval
    # remains CI/evaluation-only and absent from the production dependency set.
    if on_render:
        try:
            from docling_adapter import status as docling_status
            from r23_workflow_runtime import status as workflow_status
            from r23_deepeval_adapter import status as deepeval_status
            from r23_browser_use_adapter import status as browser_use_status
            brain=(BASE/"r23_brain.py").read_text(encoding="utf-8").lower()
            docling=docling_status()
            workflow=workflow_status()
            deepeval=deepeval_status()
            browser_use=browser_use_status()
            external_names=("docling","deepeval","langgraph","browser_use")
            helpers_ok=bool(
                docling.get("available")
                and workflow.get("langgraph_available")
                and workflow.get("no_duplicate_action_replay")
                and not deepeval.get("installed")
                and browser_use.get("scope")=="bounded_browser_executor"
                and browser_use.get("r23_final_answer_owner") is True
                and browser_use.get("lazy_loaded") is True
                and not any(x in brain for x in external_names)
            )
            add("external_capability_boundaries",helpers_ok,{
                "docling_available":bool(docling.get("available")),
                "langgraph_available":bool(workflow.get("langgraph_available")),
                "no_duplicate_action_replay":bool(workflow.get("no_duplicate_action_replay")),
                "deepeval_in_production":bool(deepeval.get("installed")),
                "browser_use_installed":bool(browser_use.get("installed")),
                "browser_use_enabled":bool(browser_use.get("enabled")),
                "browser_use_scope":browser_use.get("scope"),
                "r23_brain_external_mentions":[x for x in external_names if x in brain],
            })
        except Exception as exc:
            add("external_capability_boundaries",False,str(exc)[:240])

    passed=sum(1 for x in checks if x["passed"])
    return {
        "ok":passed==len(checks),
        "passed":passed,
        "total":len(checks),
        "checks":checks,
        "database_url_configured":database_url_configured,
    }
