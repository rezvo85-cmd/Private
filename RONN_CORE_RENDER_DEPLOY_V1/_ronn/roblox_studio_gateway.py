"""Cloud-side gateway to a paired local Roblox Studio MCP bridge.

This module never opens a socket to localhost and never imports an MCP SDK. It
places bounded tool-call jobs in the owner-scoped queue. The local bridge on the
user's computer is the only process allowed to spawn Roblox Studio's stdio MCP
server.
"""
from __future__ import annotations

import re
from typing import Any

from roblox_bridge_store import default_store, status as store_status

VERSION = "RONN-ROBLOX-STUDIO-GATEWAY-3"
MIN_BRIDGE_VERSION = (1, 1, 0)

# Official Roblox Studio MCP tools documented by Roblox. The bridge also reports
# the live tool catalog/schema, but this allowlist prevents a compromised planner
# from invoking an unexpected future/local tool without an explicit code update.
OFFICIAL_TOOL_ALLOWLIST = {
    "script_read",
    "multi_edit",
    "script_search",
    "script_grep",
    "generate_mesh",
    "generate_material",
    "generate_procedural_model",
    "wait_job_finished",
    "search_asset",
    "insert_asset",
    "upload_image",
    "store_image",
    "subagent",
    "search_game_tree",
    "inspect_instance",
    "execute_luau",
    "get_studio_state",
    "start_stop_play",
    "get_console_output",
    "screen_capture",
    "character_navigation",
    "user_keyboard_input",
    "user_mouse_input",
    "http_get",
    "skill",
    "list_roblox_studios",
}

READ_ONLY_TOOLS = {
    "script_read",
    "script_search",
    "script_grep",
    "search_game_tree",
    "inspect_instance",
    "get_studio_state",
    "get_console_output",
    "screen_capture",
    "http_get",
    "skill",
    "list_roblox_studios",
    "search_asset",
}

MUTATING_TOOLS = {
    "multi_edit",
    "execute_luau",
    "generate_mesh",
    "generate_material",
    "generate_procedural_model",
    "insert_asset",
    "upload_image",
    "store_image",
    "start_stop_play",
    "character_navigation",
    "user_keyboard_input",
    "user_mouse_input",
    "subagent",
    "wait_job_finished",
}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def bridge_compatible(version: Any) -> bool:
    text=_norm(version)
    match=re.search(r"(\d+)\.(\d+)\.(\d+)",text)
    if not match:
        return False
    return tuple(int(x) for x in match.groups()) >= MIN_BRIDGE_VERSION


def _studio_id(row: dict[str, Any]) -> str:
    return _norm(
        row.get("studio_id")
        or row.get("studioId")
        or row.get("id")
        or row.get("instance_id")
        or row.get("instanceId")
    )


def _studio_label(row: dict[str, Any]) -> str:
    return _norm(
        row.get("name")
        or row.get("label")
        or row.get("place_name")
        or row.get("placeName")
        or "Roblox Studio"
    )


def _place_id(row: dict[str, Any]) -> str:
    value = row.get("place_id")
    if value is None:
        value = row.get("placeId")
    return _norm(value)


def _online_bridge(owner: str, bridge_id: str | None = None) -> dict[str, Any] | None:
    status = default_store().status(owner)
    bridges = [
        x for x in status.get("bridges") or []
        if x.get("online") and x.get("mcp_connected") and bridge_compatible(x.get("bridge_version"))
    ]
    if bridge_id:
        return next((x for x in bridges if x.get("bridge_id") == bridge_id), None)
    selected = status.get("selected_bridge_id")
    if selected:
        hit = next((x for x in bridges if x.get("bridge_id") == selected), None)
        if hit:
            return hit
    return bridges[0] if bridges else None


def status(owner: str) -> dict[str, Any]:
    data = default_store().status(owner)
    bridges=[]
    for raw in data.get("bridges") or []:
        row=dict(raw)
        row["compatible"]=bridge_compatible(row.get("bridge_version"))
        row["upgrade_required"]=bool(
            row.get("online")
            and row.get("mcp_connected")
            and not row["compatible"]
        )
        bridges.append(row)
    online = [
        x for x in bridges
        if x.get("online") and x.get("mcp_connected") and x.get("compatible")
    ]
    return {
        "version": VERSION,
        "online": bool(online),
        "bridge_count": len(bridges),
        "online_bridge_count": len(online),
        "selected_bridge_id": data.get("selected_bridge_id"),
        "selected_studio_id": data.get("selected_studio_id"),
        "bridges": bridges,
        "transport": "outbound_https_queue_to_local_stdio_mcp",
        "minimum_bridge_version": ".".join(str(x) for x in MIN_BRIDGE_VERSION),
        "upgrade_required": any(x.get("upgrade_required") for x in bridges),
        "store": store_status(),
    }

def tool_catalog(owner: str, bridge_id: str | None = None) -> list[dict[str, Any]]:
    bridge = _online_bridge(owner, bridge_id)
    if not bridge:
        return []
    out = []
    seen = set()
    for tool in bridge.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = _norm(tool.get("name"))
        if not name or name in seen or name not in OFFICIAL_TOOL_ALLOWLIST:
            continue
        seen.add(name)
        out.append({
            "name": name,
            "description": _norm(tool.get("description"))[:1200],
            "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
        })
    return out


def studios(owner: str, bridge_id: str | None = None) -> list[dict[str, Any]]:
    bridge = _online_bridge(owner, bridge_id)
    if not bridge:
        return []
    out = []
    seen = set()
    for raw in bridge.get("studios") or []:
        if not isinstance(raw, dict):
            continue
        sid = _studio_id(raw)
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append({
            "studio_id": sid,
            "name": _studio_label(raw),
            "place_id": _place_id(raw) or None,
            "bridge_id": bridge.get("bridge_id"),
        })
    return out


def resolve_target(
    owner: str,
    *,
    message: str = "",
    bridge_id: str | None = None,
    studio_id: str | None = None,
) -> dict[str, Any]:
    bridge = _online_bridge(owner, bridge_id)
    if not bridge:
        return {
            "ok": False,
            "reason": "bridge_offline",
            "message": "RONN Roblox Bridge is not connected to Roblox Studio.",
            "studios": [],
        }

    rows = studios(owner, str(bridge.get("bridge_id")))
    if not rows:
        return {
            "ok": False,
            "reason": "no_studios",
            "message": "The bridge is online, but no Roblox Studio window is connected.",
            "bridge_id": bridge.get("bridge_id"),
            "studios": [],
        }

    explicit = _norm(studio_id)
    if explicit:
        hit = next((x for x in rows if x["studio_id"] == explicit), None)
        if hit:
            default_store().select_studio(owner, hit["bridge_id"], hit["studio_id"])
            return {"ok": True, "target": hit, "selection": "explicit", "studios": rows}
        return {
            "ok": False,
            "reason": "studio_not_found",
            "message": "The requested Studio window is no longer connected.",
            "bridge_id": bridge.get("bridge_id"),
            "studios": rows,
        }

    saved = default_store().status(owner).get("selected_studio_id")
    if saved:
        hit = next((x for x in rows if x["studio_id"] == saved), None)
        if hit:
            return {"ok": True, "target": hit, "selection": "remembered", "studios": rows}

    if len(rows) == 1:
        hit = rows[0]
        default_store().select_studio(owner, hit["bridge_id"], hit["studio_id"])
        return {"ok": True, "target": hit, "selection": "only_connected", "studios": rows}

    low = _norm(message).lower()
    scored = []
    for row in rows:
        score = 0
        name = row["name"].lower()
        place = str(row.get("place_id") or "").lower()
        if name and name in low:
            score += 8
        if place and place in low:
            score += 10
        for token in set(re.findall(r"[a-z0-9]{3,}", name)):
            if token in low:
                score += 1
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        hit = scored[0][1]
        default_store().select_studio(owner, hit["bridge_id"], hit["studio_id"])
        return {"ok": True, "target": hit, "selection": "message_match", "studios": rows}

    return {
        "ok": False,
        "reason": "multiple_studios",
        "message": "More than one Roblox Studio window is connected. Select the target once, then RONN will remember it.",
        "bridge_id": bridge.get("bridge_id"),
        "studios": rows,
    }


def select_target(owner: str, bridge_id: str, studio_id: str) -> dict[str, Any]:
    return default_store().select_studio(owner, bridge_id, studio_id)


def call_tool(
    owner: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    bridge_id: str | None = None,
    studio_id: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    name = _norm(name)
    if name not in OFFICIAL_TOOL_ALLOWLIST:
        raise ValueError("That Roblox Studio MCP tool is not allowed.")

    bridge = _online_bridge(owner, bridge_id)
    if not bridge:
        return {"ok": False, "reason": "bridge_offline", "tool": name}

    live_names = {x["name"] for x in tool_catalog(owner, str(bridge.get("bridge_id")))}
    if live_names and name not in live_names:
        return {
            "ok": False,
            "reason": "tool_unavailable",
            "tool": name,
            "available_tools": sorted(live_names),
        }

    args = dict(arguments or {})
    # Never let a model silently redirect a call to another Studio.
    args.pop("studio_id", None)
    args.pop("studioId", None)
    if name != "list_roblox_studios":
        if not studio_id:
            target = resolve_target(owner, bridge_id=str(bridge.get("bridge_id")))
            if not target.get("ok"):
                return {"ok": False, "reason": target.get("reason"), "tool": name, "target": target}
            studio_id = target["target"]["studio_id"]
        args["studio_id"] = str(studio_id)

    wait_timeout = max(8.0, min(float(timeout or 45.0), 150.0))
    # The local MCP call must finish or fail before the cloud-side wait expires,
    # otherwise RONN could report a timeout while a mutating Studio action keeps
    # running in the background. Keep a small response-delivery margin.
    tool_timeout = max(5.0, wait_timeout - 6.0)

    queued = default_store().enqueue(
        owner,
        "mcp_tool",
        {
            "name": name,
            "arguments": args,
            "tool_timeout_seconds": tool_timeout,
        },
        bridge_id=str(bridge.get("bridge_id")),
        retry_safe=bool(name in READ_ONLY_TOOLS),
    )
    row = default_store().wait(
        owner,
        queued["job_id"],
        timeout=wait_timeout,
    )
    if row.get("status") != "completed":
        retry_safe=bool(name in READ_ONLY_TOOLS)
        ambiguous_mutation=bool(
            not retry_safe
            and (row.get("status") == "uncertain" or row.get("timed_out"))
        )
        if ambiguous_mutation:
            reason="mutation_delivery_uncertain"
        elif row.get("timed_out"):
            reason="bridge_job_timeout"
        else:
            reason="bridge_job_failed"
        return {
            "ok": False,
            "reason": reason,
            "uncertain": ambiguous_mutation,
            "retry_safe": retry_safe,
            "tool": name,
            "job_id": row.get("job_id"),
            "error": row.get("error") or "",
        }
    result = row.get("result") or {}
    return {
        "ok": bool(result.get("ok", True)) and not bool(result.get("isError")),
        "tool": name,
        "job_id": row.get("job_id"),
        "bridge_id": bridge.get("bridge_id"),
        "studio_id": studio_id,
        "result": result,
    }


def refresh_studios(owner: str, *, bridge_id: str | None = None, timeout: float = 20.0) -> dict[str, Any]:
    result = call_tool(
        owner,
        "list_roblox_studios",
        {},
        bridge_id=bridge_id,
        timeout=timeout,
    )
    # The local bridge includes normalized_studios for this official tool.
    normalized = ((result.get("result") or {}).get("normalized_studios") or [])
    if normalized and result.get("bridge_id"):
        auth_status = default_store().status(owner)
        bridge = next(
            (x for x in auth_status.get("bridges") or [] if x.get("bridge_id") == result.get("bridge_id")),
            None,
        )
        # Heartbeats are the canonical catalog. The bridge itself will refresh it
        # on its next heartbeat, so do not forge bridge metadata here.
        return {"ok": result.get("ok"), "studios": normalized, "bridge": bridge, "tool_result": result}
    return {"ok": result.get("ok"), "studios": studios(owner, bridge_id), "tool_result": result}


def manual_tool_call(
    owner: str,
    name: str,
    arguments: dict[str, Any],
    *,
    bridge_id: str | None = None,
    studio_id: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    return call_tool(
        owner,
        name,
        arguments,
        bridge_id=bridge_id,
        studio_id=studio_id,
        timeout=timeout,
    )


def capability_status(owner: str | None = None) -> dict[str, Any]:
    data = {
        "version": VERSION,
        "official_studio_mcp": True,
        "transport": "local_stdio_via_outbound_paired_bridge",
        "explicit_studio_id": True,
        "multi_studio": True,
        "tool_allowlist_count": len(OFFICIAL_TOOL_ALLOWLIST),
        "read_only_tools": sorted(READ_ONLY_TOOLS),
        "mutating_tools": sorted(MUTATING_TOOLS),
        "mutation_jobs_auto_retry": False,
        "read_only_jobs_auto_retry": True,
        "stale_completion_protection": True,
        "minimum_bridge_version": ".".join(str(x) for x in MIN_BRIDGE_VERSION),
        "owns_model_routing": False,
        "owns_final_answer": False,
        "per_tool_timeout": True,
        "late_mutation_timeout_guard": True,
    }
    if owner is not None:
        data["runtime"] = status(owner)
    return data
