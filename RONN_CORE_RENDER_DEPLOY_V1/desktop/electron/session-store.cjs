const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const MAX_SESSIONS = 60;
const MAX_TASK = 12000;
const MAX_PATH = 1200;

function safeText(value, limit) {
  return String(value == null ? "" : value).replace(/[\u0000-\u001f&&[^\n\t]]/g, "").slice(0, limit);
}

function boundedObject(value, maxBytes = 160000) {
  if (value == null) return null;
  try {
    const json = JSON.stringify(value);
    if (Buffer.byteLength(json, "utf8") <= maxBytes) return JSON.parse(json);
  } catch {}
  return { truncated: true };
}

class SessionStore {
  constructor(userData) {
    this.file = path.join(userData, "roblox-sessions.json");
  }

  read() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      return Array.isArray(parsed?.sessions) ? parsed.sessions : [];
    } catch {
      return [];
    }
  }

  write(rows) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const next = {
      version: 1,
      sessions: rows
        .sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0))
        .slice(0, MAX_SESSIONS),
    };
    const tmp = this.file + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(next, null, 2), "utf8");
    try {
      fs.renameSync(tmp, this.file);
    } catch {
      fs.copyFileSync(tmp, this.file);
      fs.rmSync(tmp, { force: true });
    }
  }

  list() {
    return this.read().sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
  }

  get(id) {
    return this.read().find((row) => row.id === id) || null;
  }

  create(input = {}) {
    const now = Date.now();
    const row = {
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
      state: "running",
      task: safeText(input.task, MAX_TASK),
      selected_path: safeText(input.selected_path, MAX_PATH),
      studio_id: safeText(input.studio_id, 300),
      studio_name: safeText(input.studio_name, 300),
      place_id: safeText(input.place_id, 120),
      workspace: safeText(input.workspace, MAX_PATH),
      plan: boundedObject(input.plan),
      execution: null,
      error: "",
    };
    const rows = this.read();
    rows.unshift(row);
    this.write(rows);
    return row;
  }

  update(id, patch = {}) {
    const rows = this.read();
    const index = rows.findIndex((row) => row.id === id);
    if (index < 0) throw new Error("RONN Studio session was not found.");
    const row = { ...rows[index] };
    if (patch.state && ["running", "completed", "failed", "interrupted"].includes(patch.state)) row.state = patch.state;
    if ("plan" in patch) row.plan = boundedObject(patch.plan);
    if ("execution" in patch) row.execution = boundedObject(patch.execution);
    if ("error" in patch) row.error = safeText(patch.error, 2000);
    if ("selected_path" in patch) row.selected_path = safeText(patch.selected_path, MAX_PATH);
    row.updated_at = Date.now();
    rows[index] = row;
    this.write(rows);
    return row;
  }

  interruptRunning() {
    const rows = this.read();
    let changed = false;
    const now = Date.now();
    for (const row of rows) {
      if (row.state === "running") {
        row.state = "interrupted";
        row.error = row.error || "RONN Desktop closed before this Studio task reached a proven result.";
        row.updated_at = now;
        changed = true;
      }
    }
    if (changed) this.write(rows);
    return rows;
  }
}

module.exports = { SessionStore };
