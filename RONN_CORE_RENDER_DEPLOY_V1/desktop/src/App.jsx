import React, { useEffect, useMemo, useState } from "react";
import { RonnApi } from "./api.js";

const DEFAULT_CORE = localStorage.getItem("ronnCoreUrl") || "";

function Badge({ good, children }) {
  return <span className={"badge " + (good ? "good" : "warn")}>{children}</span>;
}

function Stage({ row }) {
  const ok = row?.ok !== false;
  return (
    <div className={"stage " + (ok ? "ok" : "bad")}>
      <b>{row?.phase || row?.name || "step"}</b>
      <span>{row?.name || row?.tool || ""}</span>
      {!ok && <small>{String(row?.error || row?.reason || "failed")}</small>}
    </div>
  );
}

function ExplorerRow({ item, selected, onSelect }) {
  const path = item.path || item.name || "(unnamed)";
  const depth = Math.min(7, Math.max(0, path.split(/[./]/).length - 1));
  return (
    <button
      className={"explorerRow " + (selected ? "selected" : "")}
      style={{ paddingLeft: 10 + depth * 12 }}
      onClick={() => onSelect(item)}
      title={path}
    >
      <span>{item.name || path.split(/[./]/).pop()}</span>
      <small>{item.class_name || "Instance"}</small>
    </button>
  );
}

export default function App() {
  const [coreUrl, setCoreUrl] = useState(DEFAULT_CORE);
  const api = useMemo(() => new RonnApi(coreUrl), [coreUrl]);
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState("");
  const [native, setNative] = useState({ bridge: {}, toolchain: {}, updater: {}, workspace: "" });
  const [remote, setRemote] = useState({ online: false, studios: [], selected_studio_id: null });
  const [events, setEvents] = useState([]);
  const [explorer, setExplorer] = useState([]);
  const [explorerPath, setExplorerPath] = useState("game");
  const [explorerQuery, setExplorerQuery] = useState("");
  const [selected, setSelected] = useState(null);
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const [plan, setPlan] = useState(null);
  const [execution, setExecution] = useState(null);
  const [checkpoints, setCheckpoints] = useState([]);
  const [checkpointLabel, setCheckpointLabel] = useState("");
  const [sessions, setSessions] = useState([]);
  const [diagnostics, setDiagnostics] = useState([]);
  const [error, setError] = useState("");

  const addEvent = (e) => setEvents((old) => [{ ...e, at: e.at || Date.now() }, ...old].slice(0, 40));

  async function refreshNative() {
    const [bridge, toolchain, updater, workspace, sessionRows, diagnosticRows] = await Promise.all([
      window.ronnDesktop.bridge.status(),
      window.ronnDesktop.toolchain.status(),
      window.ronnDesktop.updater.status(),
      window.ronnDesktop.workspace.current(),
      window.ronnDesktop.sessions.list(),
      window.ronnDesktop.diagnostics.list(30),
    ]);
    setNative({ bridge, toolchain, updater, workspace: workspace?.workspace || "" });
    setSessions(sessionRows || []);
    setDiagnostics(diagnosticRows || []);
  }

  async function refreshRemote(silent = true) {
    if (!coreUrl) return;
    try {
      const [status, studios] = await Promise.all([
        api.request("/api/roblox/status"),
        api.request("/api/roblox/studios"),
      ]);
      setRemote({ ...status, studios: studios?.studios || [] });
      if (!silent) setMessage("RONN Core and Studio status refreshed.");
    } catch (e) {
      if (!silent) setError(e.message);
      setRemote((r) => ({ ...r, online: false }));
    }
  }

  async function refreshAll() {
    await refreshNative();
    await refreshRemote(true);
  }

  useEffect(() => {
    refreshNative().catch(() => {});
    const off = window.ronnDesktop.onEvent((e) => {
      addEvent(e);
      refreshNative().catch(() => {});
    });
    const timer = setInterval(() => refreshAll().catch(() => {}), 4500);
    return () => { off?.(); clearInterval(timer); };
  }, [coreUrl]);

  useEffect(() => {
    localStorage.setItem("ronnCoreUrl", coreUrl);
  }, [coreUrl]);

  async function act(fn) {
    setError("");
    setMessage("");
    try { return await fn(); }
    catch (e) {
      const message = String(e.message || e);
      setError(message);
      window.ronnDesktop.diagnostics.report("renderer", message).catch(() => {});
      throw e;
    }
  }

  async function unlock() {
    await act(async () => {
      await api.unlock(secret);
      setSecret("");
      setMessage("RONN Desktop is connected to your owner session.");
      await refreshRemote(false);
    });
  }

  async function installBridge() {
    await act(async () => {
      setMessage("Installing the local Studio bridge…");
      await window.ronnDesktop.bridge.install();
      setMessage("Local Studio bridge installed.");
      await refreshNative();
    });
  }

  async function pairBridge() {
    await act(async () => {
      if (!coreUrl) throw new Error("Enter your RONN Core URL first.");
      const pair = await api.request("/api/roblox/pair/start", { method: "POST", body: {} });
      await window.ronnDesktop.bridge.pairAndStart({
        server: coreUrl,
        pairCode: pair.pair_code,
        name: "RONN Desktop",
      });
      setMessage("Pairing started. RONN will reconnect automatically while this app is open.");
      setTimeout(() => refreshAll().catch(() => {}), 1800);
    });
  }

  async function selectStudio(studio) {
    await act(async () => {
      await api.request("/api/roblox/select", {
        method: "POST",
        body: { bridge_id: studio.bridge_id, studio_id: studio.studio_id },
      });
      setRemote((r) => ({ ...r, selected_studio_id: studio.studio_id }));
      setMessage("Selected " + studio.name);
      await loadExplorer(studio.studio_id, studio.bridge_id);
    });
  }

  async function loadExplorer(studioId = remote.selected_studio_id, bridgeId = null) {
    await act(async () => {
      const data = await api.request("/api/roblox/explorer", {
        method: "POST",
        body: {
          path: explorerPath,
          query: explorerQuery,
          depth: 6,
          studio_id: studioId || null,
          bridge_id: bridgeId || null,
        },
      });
      setExplorer(data.items || []);
      setMessage(`Explorer loaded ${(data.items || []).length} Studio instances.`);
    });
  }

  async function runTask() {
    let localSession = null;
    await act(async () => {
      if (!task.trim()) throw new Error("Tell RONN what to do in Studio.");
      setRunning(true);
      setExecution(null);
      const studio = remote.studios?.find((s) => s.studio_id === remote.selected_studio_id);
      localSession = await window.ronnDesktop.sessions.create({
        task: task.trim(),
        selected_path: selected?.path || "",
        studio_id: studio?.studio_id || "",
        studio_name: studio?.name || "",
        place_id: studio?.place_id || "",
        workspace: native.workspace || "",
      });
      const selectedContext = selected?.path
        ? `\n\nThe user selected this exact Studio instance in RONN Desktop: ${selected.path}. Treat that as the target when relevant; inspect it before editing.`
        : "";
      const planned = await api.request("/api/studio/plan", {
        method: "POST",
        body: { task: task.trim() + selectedContext, project_context: native.workspace || "", mode: "apex" },
      });
      setPlan(planned.plan);
      await window.ronnDesktop.sessions.update(localSession.id, { plan: planned.plan });
      addEvent({ source: "r23", type: "plan", text: planned.plan?.summary || "Plan ready" });
      const result = await api.request("/api/studio/approve", {
        method: "POST",
        body: { plan_id: planned.plan_id },
      });
      setExecution(result);
      for (const call of result.calls || []) addEvent({ source: "studio", type: call.phase || "tool", text: call.name, ok: call.ok });
      await window.ronnDesktop.sessions.update(localSession.id, {
        state: result.ok ? "completed" : "failed",
        execution: {
          ok: Boolean(result.ok),
          reason: result.reason || "",
          modified: Boolean(result.modified),
          playtest_verified: Boolean(result.playtest_verified),
          assessment: result.assessment || {},
          calls: (result.calls || []).slice(-40).map((row) => ({
            phase: row.phase || "",
            name: row.name || "",
            ok: row.ok !== false,
            error: row.error || row.reason || "",
          })),
        },
      });
      setMessage(result.ok ? "RONN finished and verified the Studio task." : "RONN finished the bounded run; review the verification result below.");
      await loadExplorer().catch(() => {});
      await refreshNative();
      setRunning(false);
    }).catch(async (e) => {
      if (localSession?.id) {
        await window.ronnDesktop.sessions.update(localSession.id, { state: "failed", error: String(e.message || e) }).catch(() => {});
      }
      await refreshNative().catch(() => {});
      setRunning(false);
    });
  }

  async function reopenSession(row) {
    const full = await window.ronnDesktop.sessions.get(row.id);
    if (!full) return;
    setTask(full.task || "");
    setPlan(full.plan || null);
    setExecution(full.execution || null);
    if (full.selected_path) setSelected({ path: full.selected_path, name: full.selected_path.split(".").pop(), class_name: "" });
    setMessage(full.state === "interrupted"
      ? "Recovered an interrupted Studio task. Review it, then run again; RONN will inspect Studio before changing anything."
      : "Loaded previous Studio task.");
  }

  async function chooseWorkspace() {
    const result = await window.ronnDesktop.workspace.choose();
    if (!result.canceled) {
      await refreshNative();
      await refreshCheckpoints();
    }
  }

  async function refreshCheckpoints() {
    try { setCheckpoints(await window.ronnDesktop.workspace.checkpoints()); }
    catch { setCheckpoints([]); }
  }

  async function createCheckpoint() {
    await act(async () => {
      const cp = await window.ronnDesktop.workspace.checkpoint(checkpointLabel || "manual");
      setCheckpointLabel("");
      setMessage("Checkpoint created: " + cp.sha.slice(0, 8));
      await refreshCheckpoints();
    });
  }

  async function restoreCheckpoint(cp) {
    if (!confirm("Restore tracked workspace files to this checkpoint? RONN will create a safety checkpoint first.")) return;
    await act(async () => {
      const result = await window.ronnDesktop.workspace.restore(cp.sha);
      setMessage("Restored checkpoint. Safety checkpoint: " + result.safety_checkpoint.slice(0, 8));
      await refreshCheckpoints();
    });
  }

  async function installToolchain() {
    await act(async () => {
      setMessage("Installing verified Rokit + pinned Rojo/Wally…");
      await window.ronnDesktop.toolchain.install();
      await refreshNative();
      setMessage("Roblox toolchain installed.");
    });
  }

  const stages = execution?.calls || [];
  const selectedStudio = remote.studios?.find((s) => s.studio_id === remote.selected_studio_id);

  return (
    <div className="app">
      <header>
        <div>
          <div className="eyebrow">RONN / ROBLOX STUDIO</div>
          <h1>Studio Command Center</h1>
        </div>
        <div className="statusStrip">
          <Badge good={native.bridge?.running}>Bridge {native.bridge?.running ? "running" : "offline"}</Badge>
          <Badge good={remote.online}>Studio MCP {remote.online ? "online" : "offline"}</Badge>
          <Badge good={Boolean(native.toolchain?.rojo)}>Rojo {native.toolchain?.rojo ? "ready" : "not installed"}</Badge>
        </div>
      </header>

      {(error || message) && <div className={"notice " + (error ? "error" : "")}>{error || message}</div>}

      <main>
        <aside className="left">
          <section>
            <h2>Connection</h2>
            <label>RONN Core URL</label>
            <input value={coreUrl} onChange={(e) => setCoreUrl(e.target.value)} placeholder="https://your-ronn.onrender.com" />
            <div className="row">
              <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="Owner secret (only if required)" />
              <button onClick={unlock}>Connect</button>
            </div>
            <div className="buttonGrid">
              <button onClick={installBridge}>Install bridge</button>
              <button className="primary" onClick={pairBridge}>Pair + start</button>
              <button onClick={() => window.ronnDesktop.bridge.start().then(refreshNative).catch((e) => setError(e.message))}>Start</button>
              <button onClick={() => window.ronnDesktop.bridge.stop().then(refreshNative)}>Stop</button>
            </div>
          </section>

          <section>
            <h2>Studio windows</h2>
            <button className="wide" onClick={() => refreshRemote(false)}>Refresh Studios</button>
            <div className="studioList">
              {(remote.studios || []).map((studio) => (
                <button key={studio.studio_id} className={"studio " + (studio.studio_id === remote.selected_studio_id ? "selected" : "")} onClick={() => selectStudio(studio)}>
                  <b>{studio.name}</b>
                  <small>{studio.place_id ? "Place " + studio.place_id : studio.studio_id}</small>
                </button>
              ))}
              {!remote.studios?.length && <p className="muted">Open Studio and enable its built-in MCP server.</p>}
            </div>
          </section>

          <section>
            <h2>Toolchain</h2>
            <div className="toolRows">
              <span>Rokit <b>{native.toolchain?.rokit || "—"}</b></span>
              <span>Rojo <b>{native.toolchain?.rojo || "—"}</b></span>
              <span>Wally <b>{native.toolchain?.wally || "—"}</b></span>
            </div>
            <div className="buttonGrid">
              <button onClick={installToolchain}>Install tools</button>
              <button onClick={() => window.ronnDesktop.toolchain.installRojoPlugin().then(() => setMessage("Rojo Studio plugin installed.")).catch((e) => setError(e.message))}>Install Rojo plugin</button>
            </div>
          </section>

          <section>
            <h2>Workspace + checkpoints</h2>
            <button className="wide pathButton" onClick={chooseWorkspace}>{native.workspace || "Choose a local Roblox project folder"}</button>
            <div className="row">
              <input value={checkpointLabel} onChange={(e) => setCheckpointLabel(e.target.value)} placeholder="Checkpoint label" />
              <button onClick={createCheckpoint}>Save</button>
            </div>
            <div className="buttonGrid">
              <button onClick={refreshCheckpoints}>History</button>
              <button onClick={() => window.ronnDesktop.toolchain.startRojo(native.workspace).then(refreshNative).catch((e) => setError(e.message))}>Start Rojo</button>
              <button onClick={() => window.ronnDesktop.toolchain.stopRojo().then(refreshNative)}>Stop Rojo</button>
            </div>
            <div className="checkpointList">
              {checkpoints.map((cp) => (
                <button key={cp.sha} onClick={() => restoreCheckpoint(cp)}>
                  <b>{cp.sha.slice(0, 8)}</b><span>{cp.message}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="center">
          <div className="panelHeader">
            <div>
              <h2>Live Explorer</h2>
              <small>{selectedStudio?.name || "No Studio selected"}</small>
            </div>
            <button onClick={() => loadExplorer()}>Reload</button>
          </div>
          <div className="explorerFilters">
            <input value={explorerPath} onChange={(e) => setExplorerPath(e.target.value)} placeholder="Path, e.g. game.Workspace" />
            <input value={explorerQuery} onChange={(e) => setExplorerQuery(e.target.value)} placeholder="Optional search" />
          </div>
          <div className="explorer">
            {explorer.map((item, i) => <ExplorerRow key={(item.path || item.name) + i} item={item} selected={selected?.path === item.path} onSelect={setSelected} />)}
            {!explorer.length && <div className="empty">Select a Studio and load Explorer.</div>}
          </div>
          <div className="selection">
            <span>Selected</span>
            <b>{selected?.path || "nothing"}</b>
            <small>{selected?.class_name || ""}</small>
          </div>
        </section>

        <aside className="right">
          <section className="task">
            <h2>Tell RONN what to do</h2>
            <textarea value={task} onChange={(e) => setTask(e.target.value)} placeholder="Example: Fix the RightDash animation in AnimSaves on this selected R6 rig, preview it, then playtest the dash." />
            <button className="primary wide" disabled={running} onClick={runTask}>{running ? "RONN is working…" : "Inspect → Build → Test"}</button>
            {selected && <small className="muted">The selected Explorer instance is attached to this task.</small>}
          </section>

          <section>
            <h2>Execution</h2>
            {plan && <div className="plan"><b>{plan.title}</b><p>{plan.summary}</p></div>}
            <div className="stages">{stages.map((row, i) => <Stage row={row} key={i} />)}</div>
            {execution?.assessment && (
              <div className={"assessment " + (execution.assessment.passed ? "ok" : "bad")}>
                <b>{execution.assessment.passed ? "Verified" : "Not proven"}</b>
                <span>{execution.assessment.reason}</span>
              </div>
            )}
          </section>

          <section>
            <h2>Sessions</h2>
            <div className="sessionList">
              {sessions.slice(0, 8).map((row) => (
                <button key={row.id} onClick={() => reopenSession(row)} className={row.state === "interrupted" ? "interrupted" : ""}>
                  <b>{row.state}</b>
                  <span>{row.task || "Studio task"}</span>
                </button>
              ))}
              {!sessions.length && <p className="muted">Studio tasks will be saved here automatically.</p>}
            </div>
          </section>

          <section>
            <h2>Activity</h2>
            <div className="events">
              {events.map((e, i) => (
                <div key={i}><b>{e.source || "RONN"}</b><span>{e.text || e.type}</span></div>
              ))}
            </div>
          </section>

          <section>
            <div className="panelHeader compact">
              <h2>Local diagnostics</h2>
              <button onClick={() => window.ronnDesktop.diagnostics.clear().then(refreshNative)}>Clear</button>
            </div>
            <p className="muted">{diagnostics.length} recent scrubbed failure{diagnostics.length === 1 ? "" : "s"} stored only on this PC.</p>
            <div className="diagnostics">
              {diagnostics.slice(0, 5).map((row, i) => (
                <div key={i}><b>{row.source}</b><span>{row.message}</span></div>
              ))}
            </div>
          </section>

          <section>
            <h2>Desktop update</h2>
            <p className="muted">Status: {native.updater?.status || "idle"} {native.updater?.progress ? native.updater.progress + "%" : ""}</p>
            <div className="buttonGrid">
              <button onClick={() => window.ronnDesktop.updater.check().then(refreshNative)}>Check</button>
              <button disabled={native.updater?.status !== "ready"} onClick={() => window.ronnDesktop.updater.install()}>Install update</button>
            </div>
          </section>
        </aside>
      </main>
    </div>
  );
}
