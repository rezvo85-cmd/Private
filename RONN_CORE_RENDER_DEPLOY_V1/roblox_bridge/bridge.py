"""RONN local Roblox Studio MCP bridge.

Runs on the user's computer. It opens Roblox Studio's official stdio MCP server,
keeps one authenticated outbound HTTPS connection path to RONN Core, advertises
the live Studio/tool catalog, and executes only bounded official Studio MCP tool
jobs. R23 remains the only model/router/final-answer owner in the cloud.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VERSION = "RONN-ROBLOX-BRIDGE-1.0.0"
HEARTBEAT_SECONDS = 6.0
CATALOG_REFRESH_SECONDS = 12.0
POLL_SECONDS = 0.8
HTTP_TIMEOUT = (5, 25)

# Defense in depth: even if the cloud queue were compromised, this process
# refuses non-Roblox-MCP tool names.
ALLOWED_TOOLS = {
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


def _default_config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return root / "RONN" / "roblox_bridge.json"
    return Path.home() / ".ronn" / "roblox_bridge.json"


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _base_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if not re.match(r"^https?://", value, re.I):
        raise ValueError("RONN server must start with http:// or https://")
    if value.startswith("http://") and not (
        value.startswith("http://127.0.0.1")
        or value.startswith("http://localhost")
    ):
        raise ValueError("Remote RONN Core must use HTTPS.")
    return value


def _bridge_id(config: dict[str, Any]) -> str:
    value = str(config.get("bridge_id") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.:-]{8,120}", value):
        return value
    return "pc-" + uuid.uuid4().hex


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "RONN-Roblox-Bridge/" + VERSION,
    }


def _post(url: str, *, token: str | None = None, payload=None, timeout=HTTP_TIMEOUT):
    headers = {"Content-Type": "application/json", "User-Agent": "RONN-Roblox-Bridge/" + VERSION}
    if token:
        headers.update(_auth_headers(token))
    response = requests.post(url, headers=headers, json=payload or {}, timeout=timeout)
    if response.status_code == 401:
        raise PermissionError("RONN bridge token was rejected. Pair this bridge again.")
    response.raise_for_status()
    return response.json()


def _pair(server: str, pair_code: str, config: dict[str, Any], config_path: Path, name: str) -> dict[str, Any]:
    bridge_id = _bridge_id(config)
    result = _post(
        server + "/bridge/roblox/pair",
        payload={
            "pair_code": str(pair_code or "").strip().upper(),
            "bridge_id": bridge_id,
            "name": name,
            "metadata": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "bridge_version": VERSION,
            },
        },
    )
    token = str(result.get("token") or "").strip()
    if not token:
        raise RuntimeError("RONN did not return a bridge token.")
    config.update({
        "server": server,
        "bridge_id": bridge_id,
        "token": token,
        "name": name,
        "paired_at": int(time.time()),
    })
    _save_config(config_path, config)
    return config


def _roblox_mcp_command() -> tuple[str, list[str], dict[str, str]]:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("LOCALAPPDATA is missing.")
        mcp_bat = Path(local) / "Roblox" / "mcp.bat"
        if not mcp_bat.exists():
            raise FileNotFoundError(
                "Roblox Studio MCP launcher was not found. Update Roblox Studio, "
                "open Assistant > Manage MCP Servers, and enable Studio as MCP server."
            )
        command = os.environ.get("ComSpec") or os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "cmd.exe",
        )
        env = {
            "LOCALAPPDATA": local,
            "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
            "TEMP": os.environ.get("TEMP", local),
            "TMP": os.environ.get("TMP", local),
            "PATH": os.environ.get("PATH", ""),
        }
        return command, ["/d", "/s", "/c", str(mcp_bat)], env

    mac = Path("/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP")
    if sys.platform == "darwin" and mac.exists():
        return str(mac), [], {"PATH": os.environ.get("PATH", "")}

    raise RuntimeError("RONN Roblox Bridge currently supports Windows and macOS Studio MCP.")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json", by_alias=True))
        except TypeError:
            return _jsonable(value.model_dump(by_alias=True))
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict(by_alias=True))
        except Exception:
            pass
    return str(value)


def _tool_row(tool: Any) -> dict[str, Any]:
    raw = _jsonable(tool)
    if not isinstance(raw, dict):
        return {"name": str(getattr(tool, "name", ""))}
    name = str(raw.get("name") or getattr(tool, "name", ""))
    schema = raw.get("inputSchema")
    if schema is None:
        schema = raw.get("input_schema")
    return {
        "name": name,
        "description": str(raw.get("description") or "")[:2000],
        "inputSchema": schema if isinstance(schema, dict) else {},
    }


def _walk_for_studios(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: Any):
        if isinstance(node, str):
            text = node.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    walk(json.loads(text))
                except Exception:
                    pass
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("studios", "studio_instances", "studioInstances"):
            rows = node.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        out.append(row)
        # Some versions return the array under structuredContent/result/data.
        for key in ("structuredContent", "structured_content", "result", "data", "content"):
            if key in node:
                walk(node.get(key))

    walk(_jsonable(value))

    normalized = []
    seen = set()
    for row in out:
        sid = str(
            row.get("studio_id")
            or row.get("studioId")
            or row.get("id")
            or row.get("instance_id")
            or row.get("instanceId")
            or ""
        ).strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        place = row.get("place_id")
        if place is None:
            place = row.get("placeId")
        normalized.append({
            "studio_id": sid,
            "name": str(
                row.get("name")
                or row.get("label")
                or row.get("place_name")
                or row.get("placeName")
                or "Roblox Studio"
            )[:180],
            "place_id": str(place).strip() if place not in (None, "") else None,
        })
    return normalized


class StudioMcpConnection:
    def __init__(self):
        self.tools: list[dict[str, Any]] = []
        self.tool_names: set[str] = set()
        self.studios: list[dict[str, Any]] = []
        self.last_error = ""
        self.connected = False
        self._session: ClientSession | None = None

    async def refresh_catalog(self):
        if not self._session:
            return
        listed = await self._session.list_tools()
        tools = [_tool_row(x) for x in getattr(listed, "tools", [])]
        self.tools = [x for x in tools if x.get("name") in ALLOWED_TOOLS]
        self.tool_names = {x["name"] for x in self.tools}

        if "list_roblox_studios" in self.tool_names:
            try:
                result = await self._session.call_tool("list_roblox_studios", arguments={})
                self.studios = _walk_for_studios(result)
            except Exception as exc:
                self.last_error = "list_roblox_studios:" + exc.__class__.__name__

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._session or not self.connected:
            raise RuntimeError("Studio MCP is not connected.")
        if name not in ALLOWED_TOOLS:
            raise PermissionError("Tool is not in the RONN Roblox allowlist.")
        if self.tool_names and name not in self.tool_names:
            raise ValueError("Tool is not advertised by the connected Studio MCP server.")
        args = dict(arguments or {})
        if name != "list_roblox_studios":
            studio_id = str(args.get("studio_id") or "").strip()
            if not studio_id:
                raise ValueError("studio_id is required for Roblox Studio MCP tool calls.")
        result = await self._session.call_tool(name, arguments=args)
        payload = _jsonable(result)
        if not isinstance(payload, dict):
            payload = {"content": payload}
        payload["ok"] = not bool(payload.get("isError") or payload.get("is_error"))
        if name == "list_roblox_studios":
            payload["normalized_studios"] = _walk_for_studios(payload)
            if payload["normalized_studios"]:
                self.studios = payload["normalized_studios"]
        return payload

    async def run(self, command: str, args: list[str], env: dict[str, str], worker):
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                self._session = session
                await session.initialize()
                self.connected = True
                self.last_error = ""
                await self.refresh_catalog()
                try:
                    await worker(self)
                finally:
                    self.connected = False
                    self._session = None


async def _heartbeat(server: str, token: str, conn: StudioMcpConnection, config: dict[str, Any]):
    payload = {
        "bridge_version": VERSION,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "mcp_connected": bool(conn.connected),
        "tools": conn.tools,
        "studios": conn.studios,
        "last_error": conn.last_error[-300:],
        "name": config.get("name"),
    }
    return await asyncio.to_thread(
        _post,
        server + "/bridge/roblox/heartbeat",
        token=token,
        payload=payload,
        timeout=HTTP_TIMEOUT,
    )


async def _pull(server: str, token: str):
    data = await asyncio.to_thread(
        _post,
        server + "/bridge/roblox/jobs/pull",
        token=token,
        payload={"limit": 1},
        timeout=HTTP_TIMEOUT,
    )
    return list(data.get("jobs") or [])


async def _complete(server: str, token: str, job_id: str, *, result=None, error=""):
    return await asyncio.to_thread(
        _post,
        server + f"/bridge/roblox/jobs/{job_id}/result",
        token=token,
        payload={"result": result or {}, "error": str(error or "")[:4000]},
        timeout=HTTP_TIMEOUT,
    )


async def _connected_worker(server: str, token: str, config: dict[str, Any], conn: StudioMcpConnection):
    last_heartbeat = 0.0
    last_catalog = time.monotonic()

    while True:
        now = time.monotonic()
        if now - last_catalog >= CATALOG_REFRESH_SECONDS:
            await conn.refresh_catalog()
            last_catalog = now

        if now - last_heartbeat >= HEARTBEAT_SECONDS:
            await _heartbeat(server, token, conn, config)
            last_heartbeat = now

        jobs = await _pull(server, token)
        if not jobs:
            await asyncio.sleep(POLL_SECONDS)
            continue

        for job in jobs:
            job_id = str(job.get("job_id") or "")
            kind = str(job.get("kind") or "")
            try:
                if kind != "mcp_tool":
                    raise ValueError("Unsupported bridge job kind.")
                payload = job.get("payload") or {}
                name = str(payload.get("name") or "")
                arguments = payload.get("arguments")
                if not isinstance(arguments, dict):
                    arguments = {}
                result = await conn.call(name, arguments)
                await _complete(server, token, job_id, result=result)
                if name == "list_roblox_studios":
                    await _heartbeat(server, token, conn, config)
                    last_heartbeat = time.monotonic()
            except Exception as exc:
                message = f"{exc.__class__.__name__}: {exc}"
                conn.last_error = message[:300]
                try:
                    await _complete(server, token, job_id, error=message)
                except Exception:
                    pass


async def _run_forever(server: str, token: str, config: dict[str, Any]):
    backoff = 1.0
    while True:
        conn = StudioMcpConnection()
        try:
            command, args, env = _roblox_mcp_command()
            print("[RONN] Connecting to Roblox Studio MCP...")
            await conn.run(
                command,
                args,
                env,
                lambda active: _connected_worker(server, token, config, active),
            )
            backoff = 1.0
        except PermissionError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            conn.last_error = f"{exc.__class__.__name__}: {exc}"[:300]
            print("[RONN] Studio MCP disconnected:", conn.last_error)
            try:
                await _heartbeat(server, token, conn, config)
            except Exception:
                pass
            print(f"[RONN] Reconnecting in {backoff:.0f}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, 15.0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RONN Roblox Studio MCP bridge")
    parser.add_argument("--server", help="RONN Core URL, e.g. https://your-ronn.onrender.com")
    parser.add_argument("--pair", help="One-time pairing code shown by RONN")
    parser.add_argument("--name", default=platform.node() or "My PC", help="Name shown in RONN")
    parser.add_argument("--config", help="Optional config JSON path")
    parser.add_argument("--reset", action="store_true", help="Forget this local bridge token")
    parser.add_argument("--check", action="store_true", help="Check local Studio MCP launcher and exit")
    return parser


def main() -> int:
    args = _parser().parse_args()
    config_path = Path(args.config).expanduser() if args.config else _default_config_path()
    config = _load_config(config_path)

    if args.reset:
        try:
            config_path.unlink(missing_ok=True)
        except TypeError:
            if config_path.exists():
                config_path.unlink()
        print("[RONN] Local bridge pairing removed.")
        return 0

    if args.check:
        command, mcp_args, _env = _roblox_mcp_command()
        print("[RONN] Studio MCP launcher found:", command, *mcp_args)
        return 0

    server = _base_url(args.server or config.get("server") or "")
    config["bridge_id"] = _bridge_id(config)
    config["name"] = str(args.name or config.get("name") or platform.node() or "My PC")[:120]

    if args.pair:
        config = _pair(server, args.pair, config, config_path, config["name"])
        print("[RONN] Pairing successful.")

    token = str(config.get("token") or "").strip()
    if not token:
        print("[RONN] This bridge is not paired yet.")
        print("[RONN] In RONN, create a Roblox pairing code, then run:")
        print(f'  python bridge.py --server "{server}" --pair YOUR_CODE')
        return 2

    config["server"] = server
    _save_config(config_path, config)

    print("[RONN] Bridge:", config["bridge_id"])
    print("[RONN] Core:", server)
    print("[RONN] Open Roblox Studio and enable Assistant > Manage MCP Servers > Enable Studio as MCP server.")
    try:
        asyncio.run(_run_forever(server, token, config))
    except KeyboardInterrupt:
        print("\n[RONN] Bridge stopped.")
        return 0
    except PermissionError as exc:
        print("[RONN]", exc)
        print("[RONN] Run with --reset and pair again.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
