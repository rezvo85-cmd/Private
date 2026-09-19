import json
import os
import re
import secrets
from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core_store import (
    add_message, create_conversation, create_project, delete_conversation, delete_project,
    ensure_conversation, get_conversation, get_project, get_settings, list_conversations,
    list_projects, stats as core_stats, update_project, update_settings,
)

API_VERSION = "v1"
CORE_VERSION = "1.9.0"
router = APIRouter(prefix="/api/v1", tags=["RONN Core API v1"])
_RUNTIME: dict[str, Any] = {}


def configure(runtime: dict[str, Any]):
    _RUNTIME.clear()
    _RUNTIME.update(runtime)


def _need(name):
    fn = _RUNTIME.get(name)
    if fn is None:
        raise HTTPException(503, f"RONN Core service '{name}' is unavailable.")
    return fn


def _owner(request: Request):
    fn = _need("owner_id")
    return fn(request)


def _optional(name, default=None):
    return _RUNTIME.get(name, default)


def _sync(owner, resource_type, resource_id, op, payload):
    fn = _optional("record_sync")
    if fn:
        try: fn(owner, resource_type, resource_id, op, payload)
        except Exception: pass


def _auth(request: Request, authorization: str | None = Header(default=None)):
    """Authorize trusted service clients OR a browser owner session.

    The backend RONN_CORE_TOKEN is never exposed to browser JavaScript.
    Web/PWA clients authenticate through the HttpOnly OP session cookie issued
    by /api/v1/owner/unlock. Desktop/service clients may still use Bearer auth.
    """
    token = (os.getenv("RONN_CORE_TOKEN") or "").strip()
    if not token:
        return True

    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if supplied and secrets.compare_digest(supplied, token):
        return True

    # Same-origin web/PWA owner sessions are intentionally accepted instead
    # of placing the backend token into localStorage, HTML, or JavaScript.
    try:
        from ecosystem_store import verify_owner_session
        op_token = (
            request.headers.get("x-ronn-op-session")
            or request.cookies.get("ronn_op")
            or ""
        ).strip()
        if op_token and verify_owner_session(op_token, _owner(request)):
            return True
    except Exception:
        pass

    raise HTTPException(401, "This device needs to reconnect to RONN.")


def _chat_auth(request: Request, authorization: str | None = Header(default=None)):
    """Normal chat may run without OP when public mode is enabled.

    OP/admin/private APIs still use _auth. Public chat identities are device/client
    scoped by owner_id, so an unauthenticated device does not inherit ronn_primary.
    Any request claiming an account or OP session must still pass real owner auth.
    """
    if (request.headers.get("x-ronn-account") or "").strip() or (request.headers.get("x-ronn-op-session") or "").strip():
        return _auth(request, authorization)
    public_mode=(os.getenv("RONN_PUBLIC_MODE") or "false").strip().lower()=="true"
    if public_mode:
        return True
    return _auth(request, authorization)


class CoreFile(BaseModel):
    name: str = ""
    content: str = ""


class CoreChatBody(BaseModel):
    message: str = ""
    conversation_id: str | None = None
    project_id: str = "default"
    history: list[dict] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    files: list[CoreFile] = Field(default_factory=list)
    mode: str = "auto"
    style: str = "auto"
    project_context: str = ""
    review: bool = False
    agent_mode: bool = True
    skill_profile: str = "auto"
    client_location: dict = Field(default_factory=dict)
    project_brain_snapshot: dict = Field(default_factory=dict)
    outcome_profile: dict = Field(default_factory=dict)


class CoreProjectCreate(BaseModel):
    name: str = "Untitled project"
    description: str = ""


class CoreProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class CoreConversationCreate(BaseModel):
    project_id: str = "default"
    title: str = "New chat"


class CoreMemoryBody(BaseModel):
    text: str


class CoreMemoryUpdate(BaseModel):
    pinned: bool | None = None
    confidence: float | None = None
    category: str | None = None


class CoreTaskBody(BaseModel):
    title: str = "Task"
    prompt: str
    project_id: str = "default"
    priority: int = 50


class CoreTaskUpdate(BaseModel):
    status: str


class CoreFilesBody(BaseModel):
    project_id: str = "default"
    files: list[CoreFile] = Field(default_factory=list)
    ingest_knowledge: bool = True


class CoreSettingsPatch(BaseModel):
    response_style: str | None = None
    reasoning_mode: str | None = None
    agent_mode: bool | None = None


@router.get("/health")
def health():
    return {
        "ok": True,
        "service": "RONN Core",
        "api_version": API_VERSION,
        "core_version": CORE_VERSION,
        "build": _RUNTIME.get("build_id", "unknown"),
        "auth_required": bool((os.getenv("RONN_CORE_TOKEN") or "").strip()),
    }


@router.get("/meta")
def meta(_: bool = Depends(_auth)):
    return {
        "service": "RONN Core",
        "api_version": API_VERSION,
        "core_version": CORE_VERSION,
        "build": _RUNTIME.get("build_id", "unknown"),
        "contract": "stable-v1",
        "stream_format": "application/x-ndjson",
        "clients": ["desktop", "mobile-ready", "web-ready"],
        "auth": "bearer-token-optional-local",
    }


@router.get("/session")
def session(request: Request, _: bool = Depends(_auth)):
    owner = _owner(request)
    return {
        "client_id": owner,
        "core": {"api_version": API_VERSION, "core_version": CORE_VERSION},
        "settings": get_settings(owner),
        "stats": core_stats(owner),
    }


@router.get("/status")
def status(request: Request, _: bool = Depends(_auth)):
    owner = _owner(request)
    data = _need("status_payload")(request)
    data["core_api"] = {"version": API_VERSION, "core_version": CORE_VERSION, "stable": True}
    data["core_store"] = core_stats(owner)
    return data


@router.get("/capabilities")
def capabilities(_: bool = Depends(_auth)):
    data = _need("capabilities_payload")()
    data["core_api_v1"] = True
    data["desktop_client"] = True
    data["mobile_client_ready"] = True
    data["web_client_ready"] = True
    data["conversation_sync_contract"] = True
    data["project_sync_contract"] = True
    return data


@router.post("/chat")
def chat(body: CoreChatBody, request: Request, _: bool = Depends(_chat_auth)):
    owner = _owner(request)
    expand = _optional("expand_shortcut")
    if expand:
        try: body.message = expand(owner, body.message)
        except Exception: pass
    if (os.getenv("RONN_CREDITS_ENABLED") or "false").strip().lower() == "true":
        op_check = _optional("is_op_request", lambda req: False)
        if not op_check(request):
            consume = _optional("consume_credit")
            if consume and not consume(owner, 1):
                raise HTTPException(402, "No RONN credits remain on this account.")
    conversation = ensure_conversation(owner, body.conversation_id, body.project_id, "New chat")
    cid = conversation["conversation_id"]
    actual_project_id = conversation.get("project_id") or "default"
    settings = get_settings(owner)
    effective_style = body.style if body.style != "auto" else settings.get("response_style", "auto")
    effective_mode = body.mode if body.mode != "auto" else settings.get("reasoning_mode", "auto")
    payload = body.dict()
    payload["project_id"] = actual_project_id
    payload["style"] = effective_style
    payload["mode"] = effective_mode
    payload["agent_mode"] = bool(body.agent_mode if body.agent_mode is not None else settings.get("agent_mode", True))
    add_message(owner, cid, "user", body.message, {"project_id": actual_project_id})
    _sync(owner, "conversation", cid, "message", {"role":"user","content":body.message,"project_id":actual_project_id})

    def wrapped_stream():
        yield (json.dumps({"core":{"api_version":API_VERSION,"conversation_id":cid,"project_id":actual_project_id}}) + "\n").encode()
        answer_parts = []
        final_meta = {}
        for raw in _need("stream_chat")(owner, payload):
            if isinstance(raw, str):
                out = raw.encode()
            else:
                out = raw
            try:
                obj = json.loads(out.decode("utf-8").strip())
                if obj.get("token"):
                    answer_parts.append(str(obj["token"]))
                if obj.get("done"):
                    final_meta = {k: obj.get(k) for k in ("route","model","request_id","audit") if k in obj}
            except Exception:
                pass
            yield out
        answer = "".join(answer_parts).strip()
        if answer:
            add_message(owner, cid, "assistant", answer, final_meta)
            _sync(owner, "conversation", cid, "message", {"role":"assistant","content":answer,"project_id":actual_project_id,"meta":final_meta})

    return StreamingResponse(
        wrapped_stream(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering":"no", "X-RONN-Conversation-ID":cid, "X-RONN-Core-Version":CORE_VERSION},
    )


@router.post("/research")
def research(body: CoreChatBody, request: Request, _: bool = Depends(_chat_auth)):
    body.mode = "max"
    body.review = True
    return chat(body, request, True)


@router.post("/chat/complete")
def chat_complete(body: CoreChatBody, request: Request, _: bool = Depends(_chat_auth)):
    owner = _owner(request)
    expand = _optional("expand_shortcut")
    if expand:
        try: body.message = expand(owner, body.message)
        except Exception: pass
    if (os.getenv("RONN_CREDITS_ENABLED") or "false").strip().lower() == "true":
        op_check = _optional("is_op_request", lambda req: False)
        if not op_check(request):
            consume = _optional("consume_credit")
            if consume and not consume(owner, 1):
                raise HTTPException(402, "No RONN credits remain on this account.")
    conversation = ensure_conversation(owner, body.conversation_id, body.project_id, "New chat")
    cid = conversation["conversation_id"]
    actual_project_id = conversation.get("project_id") or "default"
    settings = get_settings(owner)
    payload = body.dict()
    payload["project_id"] = actual_project_id
    payload["style"] = body.style if body.style != "auto" else settings.get("response_style", "auto")
    payload["mode"] = body.mode if body.mode != "auto" else settings.get("reasoning_mode", "auto")
    add_message(owner, cid, "user", body.message, {"project_id":actual_project_id})
    _sync(owner,"conversation",cid,"message",{"role":"user","content":body.message,"project_id":actual_project_id})
    answer_parts=[]; final_meta={}; response_meta={}
    for raw in _need("stream_chat")(owner,payload):
        try:
            obj=json.loads((raw if isinstance(raw,str) else raw.decode("utf-8")).strip())
            if obj.get("meta") and isinstance(obj.get("meta"),dict):
                response_meta.update(obj["meta"])
            if obj.get("token"): answer_parts.append(str(obj["token"]))
            if obj.get("done"):
                final_meta={k:obj.get(k) for k in ("route","model","request_id","audit") if k in obj}
                final_meta["meta"]=response_meta
        except Exception: pass
    answer="".join(answer_parts).strip()
    if answer:
        add_message(owner,cid,"assistant",answer,final_meta)
        _sync(owner,"conversation",cid,"message",{"role":"assistant","content":answer,"project_id":actual_project_id,"meta":final_meta})
    return {"answer":answer,"conversation_id":cid,"project_id":actual_project_id,**final_meta}


@router.post("/chat/sse")
def chat_sse(body: CoreChatBody, request: Request, _: bool = Depends(_chat_auth)):
    # Mobile-friendly SSE stream. Desktop continues using the lower-overhead NDJSON route.
    owner=_owner(request)
    expand=_optional("expand_shortcut")
    if expand:
        try: body.message=expand(owner,body.message)
        except Exception: pass
    if (os.getenv("RONN_CREDITS_ENABLED") or "false").strip().lower() == "true":
        op_check=_optional("is_op_request",lambda req:False)
        if not op_check(request):
            consume=_optional("consume_credit")
            if consume and not consume(owner,1): raise HTTPException(402,"No RONN credits remain on this account.")
    conversation=ensure_conversation(owner,body.conversation_id,body.project_id,"New chat")
    cid=conversation["conversation_id"]; project_id=conversation.get("project_id") or "default"
    settings=get_settings(owner); payload=body.dict()
    payload["project_id"]=project_id
    payload["style"]=body.style if body.style!="auto" else settings.get("response_style","auto")
    payload["mode"]=body.mode if body.mode!="auto" else settings.get("reasoning_mode","auto")
    add_message(owner,cid,"user",body.message,{"project_id":project_id})
    _sync(owner,"conversation",cid,"message",{"role":"user","content":body.message,"project_id":project_id})
    def events():
        yield "event: meta\ndata: "+json.dumps({"conversation_id":cid,"project_id":project_id,"core_version":CORE_VERSION})+"\n\n"
        parts=[]; final_meta={}; response_meta={}
        for raw in _need("stream_chat")(owner,payload):
            try:
                obj=json.loads((raw if isinstance(raw,str) else raw.decode("utf-8")).strip())
            except Exception:
                continue
            if obj.get("meta") and isinstance(obj.get("meta"),dict):
                response_meta.update(obj["meta"])
            if obj.get("token"):
                parts.append(str(obj["token"])); yield "event: token\ndata: "+json.dumps({"token":obj["token"]})+"\n\n"
            if obj.get("done"):
                final_meta={k:obj.get(k) for k in ("route","model","request_id","audit") if k in obj}
                final_meta["meta"]=response_meta
        answer="".join(parts).strip()
        if answer:
            add_message(owner,cid,"assistant",answer,final_meta)
            _sync(owner,"conversation",cid,"message",{"role":"assistant","content":answer,"project_id":project_id,"meta":final_meta})
        yield "event: done\ndata: "+json.dumps({"done":True,"answer":answer,**final_meta})+"\n\n"
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@router.get("/conversations")
def conversations(request: Request, project_id: str | None = None, limit: int = 100, _: bool = Depends(_auth)):
    return {"conversations": list_conversations(_owner(request), project_id, max(1, min(limit, 200)))}


@router.post("/conversations")
def conversation_create(body: CoreConversationCreate, request: Request, _: bool = Depends(_auth)):
    owner=_owner(request); row=create_conversation(owner, body.project_id, body.title)
    _sync(owner,"conversation",row["conversation_id"],"create",row)
    return {"conversation":row}


@router.get("/conversations/{conversation_id}")
def conversation_get(conversation_id: str, request: Request, _: bool = Depends(_auth)):
    row = get_conversation(_owner(request), conversation_id, True)
    if not row:
        raise HTTPException(404, "Conversation not found.")
    return {"conversation": row}


@router.delete("/conversations/{conversation_id}")
def conversation_delete(conversation_id: str, request: Request, _: bool = Depends(_auth)):
    owner=_owner(request); ok=delete_conversation(owner, conversation_id)
    if ok:_sync(owner,"conversation",conversation_id,"delete",{})
    return {"ok":ok}


@router.get("/projects")
def projects(request: Request, _: bool = Depends(_auth)):
    return {"projects": list_projects(_owner(request))}


@router.post("/projects")
def project_create(body: CoreProjectCreate, request: Request, _: bool = Depends(_auth)):
    owner=_owner(request); project=create_project(owner, body.name, body.description)
    _sync(owner,"project",project["project_id"],"create",project)
    return {"project":project}


@router.get("/projects/{project_id}")
def project_get(project_id: str, request: Request, _: bool = Depends(_auth)):
    p = get_project(_owner(request), project_id)
    if not p:
        raise HTTPException(404, "Project not found.")
    return {"project": p}


@router.patch("/projects/{project_id}")
def project_patch(project_id: str, body: CoreProjectUpdate, request: Request, _: bool = Depends(_auth)):
    p = update_project(_owner(request), project_id, body.name, body.description)
    if not p:
        raise HTTPException(404, "Project not found.")
    _sync(_owner(request),"project",project_id,"update",p)
    return {"project": p}


@router.delete("/projects/{project_id}")
def project_delete(project_id: str, request: Request, _: bool = Depends(_auth)):
    if project_id == "default":
        raise HTTPException(400, "The default project cannot be deleted.")
    owner=_owner(request); ok=delete_project(owner, project_id)
    if ok:_sync(owner,"project",project_id,"delete",{})
    return {"ok":ok}


@router.get("/projects/{project_id}/knowledge")
def project_knowledge(project_id: str, request: Request, q: str = "", limit: int = 8, _: bool = Depends(_auth)):
    return _need("knowledge_search")(_owner(request), q, project_id, limit)


@router.get("/memory")
def memory_get(request: Request, _: bool = Depends(_auth)):
    return {"memories": _need("list_memories")(_owner(request))}


@router.post("/memory")
def memory_post(body: CoreMemoryBody, request: Request, _: bool = Depends(_auth)):
    owner = _owner(request)
    if not body.text.strip():
        raise HTTPException(400, "Memory cannot be empty.")
    if not _need("add_memory")(owner, body.text):
        raise HTTPException(400, "RONN will not store secrets such as passwords or API keys.")
    _sync(owner,"memory","latest","create",{"text":body.text})
    return {"ok": True, "memories": _need("list_memories")(owner)}


@router.patch("/memory/{memory_id}")
def memory_patch(memory_id: int, body: CoreMemoryUpdate, request: Request, _: bool = Depends(_auth)):
    patch=body.dict(exclude_none=True); out=_need("memory_update")(request, memory_id, patch)
    _sync(_owner(request),"memory",str(memory_id),"update",patch); return out


@router.delete("/memory/{memory_id}")
def memory_delete(memory_id: int, request: Request, _: bool = Depends(_auth)):
    owner = _owner(request)
    ok=_need("delete_memory")(owner, memory_id)
    if ok:_sync(owner,"memory",str(memory_id),"delete",{})
    return {"ok":ok, "memories": _need("list_memories")(owner)}


@router.get("/tasks")
def tasks(request: Request, status: str | None = None, limit: int = 50, _: bool = Depends(_auth)):
    owner = _owner(request)
    return {"tasks": _need("queue_list")(owner, status, max(1, min(limit, 100))), "stats": _need("queue_stats")(owner)}


@router.post("/tasks")
def tasks_post(body: CoreTaskBody, request: Request, _: bool = Depends(_auth)):
    owner = _owner(request)
    item_id = _need("queue_add")(owner, body.project_id, body.title, body.prompt, body.priority)
    _sync(owner,"task",str(item_id),"create",body.dict())
    return {"ok": True, "id": item_id, "tasks": _need("queue_list")(owner, None, 50)}


@router.patch("/tasks/{task_id}")
def tasks_patch(task_id: int, body: CoreTaskUpdate, request: Request, _: bool = Depends(_auth)):
    owner = _owner(request); ok=_need("queue_update")(owner, task_id, body.status)
    if ok:_sync(owner,"task",str(task_id),"update",{"status":body.status})
    return {"ok":ok, "tasks": _need("queue_list")(owner, None, 50)}


@router.post("/files/index")
def files_index(body: CoreFilesBody, request: Request, _: bool = Depends(_auth)):
    owner = _owner(request)
    return _need("index_files_core")(owner, body.project_id, body.files, body.ingest_knowledge)


@router.get("/providers")
def providers(_: bool = Depends(_auth)):
    return _need("providers_payload")()


@router.get("/providers/check")
def providers_check(provider: str = "groq", _: bool = Depends(_auth)):
    return _need("provider_check")(provider)


@router.get("/repair-plan")
def repair_plan(_: bool = Depends(_auth)):
    return _need("repair_plan")()


@router.get("/diagnostics")
def diagnostics(request: Request, _: bool = Depends(_auth)):
    data = _need("diagnostics_payload")(request)
    data["core_api"] = {"api_version": API_VERSION, "core_version": CORE_VERSION, "store": core_stats(_owner(request))}
    return data


@router.get("/settings")
def settings_get(request: Request, _: bool = Depends(_auth)):
    return {"settings": get_settings(_owner(request))}


@router.patch("/settings")
def settings_patch(body: CoreSettingsPatch, request: Request, _: bool = Depends(_auth)):
    patch = body.dict(exclude_none=True); owner=_owner(request)
    settings=update_settings(owner, patch); _sync(owner,"settings","main","update",settings)
    return {"settings":settings}
