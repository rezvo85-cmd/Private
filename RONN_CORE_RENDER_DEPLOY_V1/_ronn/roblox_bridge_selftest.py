"""Deterministic smoke tests for RONN's Roblox Studio MCP integration.

No Roblox process, provider key, or network is required. This validates the cloud
queue/auth boundary, exact Studio targeting, R23 routing, and the bounded
inspect/edit/playtest state machine with a fake MCP transport.
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from roblox_bridge_store import RobloxBridgeStore
import roblox_studio_gateway as gateway
import roblox_studio_agent as agent
from r23_brain import plan as r23_plan


def test_store_and_gateway():
    with tempfile.TemporaryDirectory() as td:
        store=RobloxBridgeStore(Path(td)/"bridge.db")
        owner="owner_ci_1234"

        pair=store.start_pairing(owner)
        assert len(pair["pair_code"]) == 12
        paired=store.pair_bridge(
            pair["pair_code"],
            "pc-12345678",
            "CI PC",
            {"platform":"ci"},
        )
        token=paired["token"]
        assert store.authenticate(token)["owner"] == owner

        # Pairing codes are one-time.
        try:
            store.pair_bridge(pair["pair_code"],"pc-87654321","bad",{})
            raise AssertionError("pair code unexpectedly reused")
        except ValueError:
            pass

        tools=[
            {"name":"list_roblox_studios","description":"list","inputSchema":{"type":"object","properties":{}}},
            {"name":"get_studio_state","description":"state","inputSchema":{"type":"object","properties":{"studio_id":{"type":"string"}},"required":["studio_id"]}},
            {"name":"multi_edit","description":"edit","inputSchema":{"type":"object","properties":{"studio_id":{"type":"string"},"edits":{"type":"array"}},"required":["studio_id","edits"]}},
        ]
        studios=[{"studio_id":"studio-ci-1","name":"CI Place","place_id":"123"}]
        store.heartbeat(token,{
            "bridge_version":"ci",
            "mcp_connected":True,
            "tools":tools,
            "studios":studios,
        })
        status=store.status(owner)
        assert status["online"] is True
        assert status["bridges"][0]["studios"][0]["studio_id"] == "studio-ci-1"

        original_default=gateway.default_store
        gateway.default_store=lambda: store
        try:
            resolved=gateway.resolve_target(owner,message="fix my CI Place")
            assert resolved["ok"] is True
            assert resolved["target"]["studio_id"] == "studio-ci-1"
            assert store.status(owner)["selected_studio_id"] == "studio-ci-1"

            worker_error=[]
            def worker():
                try:
                    deadline=time.time()+3
                    while time.time()<deadline:
                        jobs=store.pull(token,limit=1)
                        if not jobs:
                            time.sleep(.02)
                            continue
                        job=jobs[0]
                        assert job["kind"] == "mcp_tool"
                        payload=job["payload"]
                        assert payload["name"] == "get_studio_state"
                        assert payload["arguments"]["studio_id"] == "studio-ci-1"
                        store.complete(token,job["job_id"],result={
                            "ok":True,
                            "content":[{"type":"text","text":"Edit"}],
                        })
                        return
                    raise AssertionError("gateway job was never queued")
                except Exception as exc:
                    worker_error.append(exc)

            thread=threading.Thread(target=worker,daemon=True)
            thread.start()
            result=gateway.call_tool(
                owner,
                "get_studio_state",
                {},
                bridge_id="pc-12345678",
                studio_id="studio-ci-1",
                timeout=3,
            )
            thread.join(timeout=3)
            if worker_error:
                raise worker_error[0]
            assert result["ok"] is True, result
            assert result["studio_id"] == "studio-ci-1"

            # Unexpected/non-Roblox tools are rejected before a job reaches the PC.
            try:
                gateway.call_tool(owner,"shell_exec",{},studio_id="studio-ci-1")
                raise AssertionError("non-allowlisted MCP tool was accepted")
            except ValueError:
                pass
        finally:
            gateway.default_store=original_default

        assert store.revoke(owner,"pc-12345678") == 1
        assert store.authenticate(token) is None


def test_r23_routing():
    generic=r23_plan(
        "What is Roblox Studio?",
        history=[],
        file_names=[],
        has_images=False,
        has_project=False,
        agent_mode=True,
        explicit_mode="auto",
    )
    assert generic["profile"] == "roblox"
    assert generic["capabilities"]["roblox_studio"] is False

    action=r23_plan(
        "Fix my Roblox Studio combat scripts, playtest them, and make sure there are no errors.",
        history=[],
        file_names=[],
        has_images=False,
        has_project=True,
        agent_mode=True,
        explicit_mode="auto",
    )
    caps=action["capabilities"]
    assert action["profile"] == "roblox"
    assert action["tool_mode"] == "roblox"
    assert action["needs_tools"] is True
    assert caps["roblox_studio"] is True
    assert caps["roblox_studio_mutate"] is True
    assert caps["roblox_studio_verify"] is True
    assert action["verify"] is True
    assert any(x.get("id") == "operate_roblox_studio" for x in action["task_graph"]["nodes"])


def test_bounded_studio_agent():
    originals={
        "status":agent.studio.status,
        "resolve_target":agent.studio.resolve_target,
        "tool_catalog":agent.studio.tool_catalog,
        "call_tool":agent.studio.call_tool,
    }
    calls=[]

    catalog=[
        {"name":"get_studio_state","description":"","inputSchema":{}},
        {"name":"script_read","description":"","inputSchema":{}},
        {"name":"multi_edit","description":"","inputSchema":{}},
        {"name":"start_stop_play","description":"","inputSchema":{}},
        {"name":"get_console_output","description":"","inputSchema":{}},
    ]
    target={"bridge_id":"pc-ci-agent","studio_id":"studio-agent-1","name":"Agent Place","place_id":"321"}

    def fake_model(messages,max_tokens=1600):
        system=messages[0]["content"]
        if "phase inspection" in system:
            return '{"summary":"inspect","calls":[{"name":"script_read","arguments":{"path":"ServerScriptService/Main"}}]}'
        if "phase edit" in system or "phase repair" in system:
            return '{"summary":"edit","calls":[{"name":"multi_edit","arguments":{"edits":[{"path":"ServerScriptService/Main","newText":"-- fixed"}]}}]}'
        if "phase verification" in system:
            return '{"summary":"verify","calls":[{"name":"start_stop_play","arguments":{"mode":"start"}},{"name":"get_console_output","arguments":{}}],"cleanup_calls":[{"name":"start_stop_play","arguments":{"mode":"stop"}}]}'
        if "evidence-only Roblox verification judge" in system:
            return '{"passed":true,"reason":"Play mode ran and Output was checked with no reported failure.","repairable":false}'
        raise AssertionError("unexpected model phase")

    try:
        agent.studio.status=lambda owner: {"online":True}
        agent.studio.resolve_target=lambda owner,**kwargs: {"ok":True,"target":target,"studios":[target]}
        agent.studio.tool_catalog=lambda owner,bridge_id=None: catalog

        def fake_call(owner,name,arguments,**kwargs):
            calls.append((name,dict(arguments),dict(kwargs)))
            return {
                "ok":True,
                "tool":name,
                "studio_id":kwargs.get("studio_id"),
                "result":{"ok":True,"content":[{"type":"text","text":"ok"}]},
            }
        agent.studio.call_tool=fake_call

        result=agent.run(
            "owner-ci",
            "Fix my Roblox Studio script and playtest it to make sure it works.",
            model_fn=fake_model,
            depth="deep",
        )
        assert result["available"] is True
        assert result["modified"] is True
        assert result["verification_attempted"] is True
        assert result["playtest_verified"] is True
        assert result["ok"] is True
        assert result["rollback_ready"] is True
        assert result["repair_passes"] == 0
        assert all(x[2].get("studio_id") == "studio-agent-1" for x in calls)
        names=[x[0] for x in calls]
        assert "script_read" in names
        assert "multi_edit" in names
        assert "start_stop_play" in names
        assert "get_console_output" in names
    finally:
        agent.studio.status=originals["status"]
        agent.studio.resolve_target=originals["resolve_target"]
        agent.studio.tool_catalog=originals["tool_catalog"]
        agent.studio.call_tool=originals["call_tool"]


def run():
    test_store_and_gateway()
    test_r23_routing()
    test_bounded_studio_agent()
    print("RONN Roblox Studio MCP selftest: PASS")
    return True


if __name__ == "__main__":
    run()
