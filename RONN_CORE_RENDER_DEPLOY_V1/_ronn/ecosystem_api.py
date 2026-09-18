from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from owner_auth import owner_name, verify_secret
from ecosystem_store import (
    action_by_id,
    actions,
    backup_all,
    claim_handoff,
    clipboard_latest,
    clipboard_push,
    collaborator_invite,
    collaborators,
    create_handoff,
    create_owner_session,
    credits,
    flags,
    generate_recovery_codes,
    list_backups,
    list_devices,
    list_handoffs,
    list_permissions,
    mark_undone,
    notification_read,
    notifications,
    plugin_manifests,
    pull_sync,
    record_sync,
    register_device,
    revoke_device,
    revoke_owner_session,
    routine_save,
    routines,
    set_flag,
    set_permission,
    shortcut_set,
    shortcuts,
    status,
    use_recovery_code,
    vault_delete,
    vault_get,
    vault_list,
    vault_put,
    verify_owner_session,
    workflow_save,
    workflow_get,
    workflows,
    workspace_create,
    workspaces,
)

router = APIRouter(prefix="/api/v1", tags=["RONN Ecosystem"])
_RUNTIME: dict[str, Any] = {}


def configure(runtime):
    _RUNTIME.clear()
    _RUNTIME.update(runtime or {})


def _owner(request):
    return _RUNTIME["owner_id"](request)


def _op_token(request):
    return (request.headers.get("x-ronn-op-session") or request.cookies.get("ronn_op") or "").strip()


def is_op(request):
    return verify_owner_session(_op_token(request), _owner(request))


def require_op(request: Request):
    if not is_op(request):
        raise HTTPException(403, "OP / Owner access required.")
    return True


class UnlockBody(BaseModel):
    secret: str
    device_id: str = ""
    device_name: str = "RONN Desktop"
    platform: str = "desktop"
    app_version: str = "R10"
    return_token: bool = False


class RecoveryUnlockBody(BaseModel):
    code: str
    device_id: str = ""
    device_name: str = "RONN device"
    platform: str = "unknown"
    return_token: bool = False


class DeviceBody(BaseModel):
    device_id: str
    name: str = "RONN device"
    platform: str = "unknown"
    app_version: str = ""
    push_token: str = ""


class PermissionBody(BaseModel):
    allowed: bool


class SyncPushBody(BaseModel):
    events: list[dict] = Field(default_factory=list)


class VaultBody(BaseModel):
    title: str = "Secure note"
    text: str
    item_id: str | None = None


class HandoffBody(BaseModel):
    source_device: str = ""
    target_device: str = ""
    kind: str = "context"
    payload: dict = Field(default_factory=dict)


class ClipboardBody(BaseModel):
    device_id: str = ""
    kind: str = "text"
    payload: str


class WorkflowBody(BaseModel):
    name: str
    steps: list[dict] = Field(default_factory=list)
    workflow_id: str | None = None


class RoutineBody(BaseModel):
    name: str
    interval_minutes: int = 1440
    prompt: str = ""
    workflow_id: str = ""
    routine_id: str | None = None


class ShortcutBody(BaseModel):
    alias: str
    prompt: str


class SandboxBody(BaseModel):
    language: str = "text"
    code: str
    label: str = "sandbox"


class ShareIntakeBody(BaseModel):
    text: str = ""
    url: str = ""
    source: str = "mobile"
    device_id: str = ""


class WorkspaceBody(BaseModel):
    name: str


class CollaboratorBody(BaseModel):
    subject: str
    role: str = "viewer"


class FlagBody(BaseModel):
    enabled: bool


@router.get("/owner/status")
def owner_status(request: Request):
    active = is_op(request)
    return {
        "owner_name": owner_name(),
        "op_active": active,
        "entitlements": {
            "credit_bypass": active,
            "all_models": active,
            "admin": active,
            "developer_console": active,
        },
        "credits": credits(_owner(request), active),
    }


@router.post("/owner/unlock")
def owner_unlock(body: UnlockBody, request: Request, response: Response):
    if not verify_secret(body.secret):
        raise HTTPException(401, "Invalid OP access code.")
    owner = _owner(request)
    device_id = body.device_id or request.headers.get("x-ronn-device") or ""
    if device_id:
        register_device(owner, device_id, body.device_name, body.platform, body.app_version, True)
    token, expires = create_owner_session(owner, request.headers.get("x-ronn-client", ""), device_id, 30)
    response.set_cookie(
        "ronn_op",
        token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"),
        path="/",
    )
    return {
        "ok": True,
        "owner_name": owner_name(),
        "op_active": True,
        "expires": expires,
        "session_token": token if body.return_token else None,
        "entitlements": {"credit_bypass": True, "all_models": True, "admin": True, "developer_console": True},
    }


@router.post("/owner/recovery-unlock")
def recovery_unlock(body: RecoveryUnlockBody, request: Request, response: Response):
    owner = _owner(request)
    if not use_recovery_code(owner, body.code):
        raise HTTPException(401, "Invalid or already-used recovery code.")
    if body.device_id:
        register_device(owner, body.device_id, body.device_name, body.platform, "recovery", True)
    token, expires = create_owner_session(owner, request.headers.get("x-ronn-client", ""), body.device_id, 7)
    response.set_cookie("ronn_op", token, max_age=7 * 86400, httponly=True, samesite="lax", secure=(request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"), path="/")
    return {"ok": True, "op_active": True, "expires": expires, "session_token": token if body.return_token else None}


@router.post("/owner/lock")
def owner_lock(request: Request, response: Response):
    token = _op_token(request)
    if token:
        revoke_owner_session(token)
    response.delete_cookie("ronn_op", path="/")
    return {"ok": True, "op_active": False}


@router.post("/owner/recovery-codes")
def recovery_codes(request: Request, _=Depends(require_op)):
    return {
        "codes": generate_recovery_codes(_owner(request), 8),
        "warning": "These one-time codes are shown only in this response. Store them somewhere safe.",
    }


@router.get("/account")
def account(request: Request):
    active = is_op(request)
    return {
        "account_id": _owner(request),
        "display_name": owner_name() if active else "RONN User",
        "role": "owner" if active else "user",
        "op_active": active,
        "credits": credits(_owner(request), active),
        "cloud_ready": True,
    }


@router.get("/devices")
def devices_get(request: Request, _=Depends(require_op)):
    return {"devices": list_devices(_owner(request))}


@router.post("/devices/register")
def devices_register(body: DeviceBody, request: Request):
    return {
        "device": register_device(
            _owner(request),
            body.device_id,
            body.name,
            body.platform,
            body.app_version,
            is_op(request),
            body.push_token,
        )
    }


@router.delete("/devices/{device_id}")
def devices_revoke(device_id: str, request: Request, _=Depends(require_op)):
    return {"ok": revoke_device(_owner(request), device_id)}


@router.get("/devices/{device_id}/permissions")
def permissions_get(device_id: str, request: Request, _=Depends(require_op)):
    return {"permissions": list_permissions(_owner(request), device_id)}


@router.patch("/devices/{device_id}/permissions/{permission}")
def permissions_patch(device_id: str, permission: str, body: PermissionBody, request: Request, _=Depends(require_op)):
    return {"ok": set_permission(_owner(request), device_id, permission, body.allowed)}


@router.get("/sync/pull")
def sync_pull(request: Request, since: int = 0, limit: int = 500):
    return pull_sync(_owner(request), since, limit)


@router.post("/sync/push")
def sync_push(body: SyncPushBody, request: Request):
    owner = _owner(request)
    accepted = 0
    allowed = {"handoff", "clipboard", "device_preference", "mobile_draft"}
    for event in body.events[:200]:
        resource_type = str(event.get("resource_type") or "")
        if resource_type not in allowed:
            continue
        record_sync(
            owner,
            resource_type,
            str(event.get("resource_id") or "mobile"),
            str(event.get("op") or "upsert"),
            event.get("payload") or {},
        )
        accepted += 1
    return {"accepted": accepted}


@router.get("/actions")
def actions_get(request: Request, limit: int = 100, _=Depends(require_op)):
    return {"actions": actions(_owner(request), limit)}


@router.post("/actions/{action_id}/undo")
def actions_undo(action_id: int, request: Request, _=Depends(require_op)):
    owner = _owner(request)
    action = action_by_id(owner, action_id)
    if not action or not action.get("reversible") or action.get("undone"):
        raise HTTPException(400, "This action cannot be undone.")
    inverse = action.get("inverse") or {}
    if inverse.get("type") == "feature_flag":
        set_flag(owner, inverse.get("flag"), bool(inverse.get("enabled")))
    else:
        raise HTTPException(400, "No undo handler is available for this action yet.")
    mark_undone(owner, action_id)
    return {"ok": True}


@router.get("/vault")
def vault_index(request: Request, _=Depends(require_op)):
    return {"items": vault_list(_owner(request))}


@router.post("/vault")
def vault_write(body: VaultBody, request: Request, _=Depends(require_op)):
    return {"item": vault_put(_owner(request), body.title, body.text, body.item_id)}


@router.get("/vault/{item_id}")
def vault_read(item_id: str, request: Request, _=Depends(require_op)):
    item = vault_get(_owner(request), item_id)
    if not item:
        raise HTTPException(404, "Vault item not found or could not be decrypted.")
    return {"item": item}


@router.delete("/vault/{item_id}")
def vault_remove(item_id: str, request: Request, _=Depends(require_op)):
    return {"ok": vault_delete(_owner(request), item_id)}


@router.get("/handoffs")
def handoffs_get(request: Request, status: str = "pending"):
    return {"handoffs": list_handoffs(_owner(request), status)}


@router.post("/handoffs")
def handoffs_post(body: HandoffBody, request: Request):
    return {"id": create_handoff(_owner(request), body.source_device, body.kind, body.payload, body.target_device)}


@router.post("/handoffs/{handoff_id}/claim")
def handoffs_claim(handoff_id: str, request: Request, device_id: str = ""):
    row = claim_handoff(_owner(request), handoff_id, device_id)
    if not row:
        raise HTTPException(404, "Handoff not found.")
    return {"handoff": row}


@router.get("/clipboard")
def clip_get(request: Request, after_id: int = 0):
    return {"item": clipboard_latest(_owner(request), after_id)}


@router.post("/clipboard")
def clip_post(body: ClipboardBody, request: Request):
    return {"id": clipboard_push(_owner(request), body.device_id, body.payload, body.kind)}


@router.get("/notifications")
def notifications_get(request: Request, unread_only: bool = False):
    return {"notifications": notifications(_owner(request), unread_only)}


@router.post("/notifications/{notification_id}/read")
def notifications_mark(notification_id: int, request: Request):
    return {"ok": notification_read(_owner(request), notification_id)}


@router.get("/workflows")
def workflows_get(request: Request):
    return {"workflows": workflows(_owner(request))}


@router.post("/workflows")
def workflows_post(body: WorkflowBody, request: Request):
    return {"id": workflow_save(_owner(request), body.name, body.steps, body.workflow_id)}


@router.post("/workflows/{workflow_id}/run")
def workflows_run(workflow_id: str, request: Request):
    owner = _owner(request)
    wf = workflow_get(owner, workflow_id)
    if not wf or not wf.get("enabled"):
        raise HTTPException(404, "Workflow not found or disabled.")
    queue_add = _RUNTIME.get("queue_add")
    if not queue_add:
        raise HTTPException(503, "Task queue is unavailable.")
    queued = []
    for i, step in enumerate((wf.get("steps") or [])[:40], start=1):
        if not isinstance(step, dict):
            continue
        kind = str(step.get("type") or step.get("kind") or "prompt").lower()
        if kind not in {"prompt", "task", "chat"}:
            continue
        prompt = str(step.get("prompt") or step.get("text") or "").strip()
        if not prompt:
            continue
        title = str(step.get("title") or f"{wf.get('name','Workflow')} · step {i}")[:160]
        project_id = str(step.get("project_id") or "default")[:120]
        priority = int(step.get("priority") or 50)
        queued.append(queue_add(owner, project_id, title, prompt, priority))
    record_sync(owner, "workflow", workflow_id, "run", {"queued": queued})
    return {"ok": True, "workflow_id": workflow_id, "queued_task_ids": queued}


@router.post("/sandbox/analyze")
def sandbox_analyze(body: SandboxBody, request: Request):
    # Safe-by-default: static analysis only. This route never executes submitted code.
    code = (body.code or "")[:120000]
    checker = _RUNTIME.get("code_sanity")
    issues = checker(body.language, code) if checker else []
    digest = __import__("hashlib").sha256(code.encode("utf-8", errors="ignore")).hexdigest()
    log = _RUNTIME.get("log_action")
    if log:
        try:
            log(_owner(request), "sandbox.analyze", body.label, {"language": body.language, "sha256": digest, "issues": len(issues)}, None)
        except Exception:
            pass
    return {"ok": True, "executed": False, "mode": "static_analysis", "sha256": digest, "issues": issues}


@router.post("/share/intake")
def share_intake(body: ShareIntakeBody, request: Request):
    owner = _owner(request)
    payload = {"text": body.text[:20000], "url": body.url[:4000], "source": body.source[:80], "device_id": body.device_id[:160]}
    record_sync(owner, "mobile_draft", body.device_id or "mobile", "share_intake", payload)
    return {"ok": True, "draft": payload}


@router.get("/quick-actions")
def quick_actions(request: Request):
    return {"actions": [
        {"id": "new_chat", "deep_link": "ronn://new", "native_ready": True},
        {"id": "camera", "deep_link": "ronn://camera", "native_ready": True},
        {"id": "share", "deep_link": "ronn://share", "native_ready": True},
        {"id": "widget", "deep_link": "ronn://new", "native_ready": False},
        {"id": "lock_screen", "deep_link": "ronn://new", "native_ready": False},
    ]}


@router.get("/routines")
def routines_get(request: Request):
    return {"routines": routines(_owner(request))}


@router.post("/routines")
def routines_post(body: RoutineBody, request: Request):
    return {"id": routine_save(_owner(request), body.name, body.interval_minutes, body.prompt, body.workflow_id, body.routine_id)}


@router.get("/shortcuts")
def shortcuts_get(request: Request):
    return {"shortcuts": shortcuts(_owner(request))}


@router.post("/shortcuts")
def shortcuts_post(body: ShortcutBody, request: Request):
    return {"ok": shortcut_set(_owner(request), body.alias, body.prompt)}


@router.get("/workspaces")
def workspace_get(request: Request):
    return {"workspaces": workspaces(_owner(request))}


@router.post("/workspaces")
def workspace_post(body: WorkspaceBody, request: Request):
    return {"id": workspace_create(_owner(request), body.name)}


@router.get("/workspaces/{workspace_id}/collaborators")
def collaborators_get(workspace_id: str, request: Request, _=Depends(require_op)):
    return {"collaborators": collaborators(_owner(request), workspace_id)}


@router.post("/workspaces/{workspace_id}/collaborators")
def collaborators_post(workspace_id: str, body: CollaboratorBody, request: Request, _=Depends(require_op)):
    return {"ok": collaborator_invite(_owner(request), workspace_id, body.subject, body.role)}


@router.get("/feature-flags")
def flags_get(request: Request):
    return {"flags": flags(_owner(request))}


@router.patch("/feature-flags/{flag}")
def flags_patch(flag: str, body: FlagBody, request: Request, _=Depends(require_op)):
    return {"ok": set_flag(_owner(request), flag, body.enabled), "flags": flags(_owner(request))}


@router.post("/backups")
def backup_create(request: Request, _=Depends(require_op)):
    return {"backup": backup_all("manual")}


@router.get("/backups")
def backup_list(request: Request, _=Depends(require_op)):
    return {"backups": list_backups()}


@router.get("/plugins")
def plugins_get(request: Request):
    return {"plugins": plugin_manifests()}


@router.get("/ecosystem/status")
def ecosystem_status(request: Request):
    data = status(_owner(request), is_op(request))
    data["build"] = _RUNTIME.get("build_id", "")
    data["core_version"] = "1.1.0"
    data["sync_status"] = "ready"
    return data
