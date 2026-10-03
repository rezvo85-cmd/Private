const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

function run(cmd, args, cwd, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd, windowsHide: true });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve({ ok: false, code: -1, stdout, stderr: stderr + "\nTimed out." });
    }, timeoutMs);
    child.stdout.on("data", (d) => { stdout += d.toString(); });
    child.stderr.on("data", (d) => { stderr += d.toString(); });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, code: -1, stdout, stderr: String(err.message || err) });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, stdout, stderr });
    });
  });
}

async function ensureRepo(workspace) {
  if (!workspace || !fs.existsSync(workspace)) throw new Error("Choose a valid Roblox workspace first.");
  const probe = await run("git", ["rev-parse", "--is-inside-work-tree"], workspace);
  if (!probe.ok) {
    const init = await run("git", ["init"], workspace);
    if (!init.ok) throw new Error("Git is required for checkpoints. " + init.stderr);
    await run("git", ["config", "user.name", "RONN Checkpoint"], workspace);
    await run("git", ["config", "user.email", "ronn-checkpoint@localhost"], workspace);
  }
  return true;
}

async function checkpoint(workspace, label = "") {
  await ensureRepo(workspace);
  await run("git", ["add", "-A"], workspace);
  const safe = String(label || "Studio checkpoint").replace(/[\r\n]+/g, " ").slice(0, 120);
  const commit = await run("git", ["commit", "--allow-empty", "-m", "RONN checkpoint: " + safe], workspace);
  if (!commit.ok) throw new Error(commit.stderr || "Checkpoint commit failed.");
  const sha = await run("git", ["rev-parse", "HEAD"], workspace);
  return { ok: true, sha: sha.stdout.trim(), message: safe };
}

async function list(workspace) {
  await ensureRepo(workspace);
  const out = await run("git", ["log", "--pretty=format:%H%x09%ct%x09%s", "-n", "30"], workspace);
  if (!out.ok) return [];
  return out.stdout.split(/\r?\n/).filter(Boolean).map((line) => {
    const [sha, ts, ...rest] = line.split("\t");
    return { sha, timestamp: Number(ts || 0), message: rest.join("\t") };
  });
}

async function restore(workspace, sha) {
  await ensureRepo(workspace);
  if (!/^[0-9a-f]{7,40}$/i.test(String(sha || ""))) throw new Error("Invalid checkpoint id.");
  const safety = await checkpoint(workspace, "automatic pre-restore safety checkpoint");
  const restoreResult = await run("git", ["restore", "--source=" + sha, "--staged", "--worktree", "."], workspace, 60000);
  if (!restoreResult.ok) throw new Error(restoreResult.stderr || "Restore failed.");
  return { ok: true, restored: sha, safety_checkpoint: safety.sha };
}

module.exports = { checkpoint, list, restore, run };
