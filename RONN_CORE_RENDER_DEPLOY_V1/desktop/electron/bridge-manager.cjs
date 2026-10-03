const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const EventEmitter = require("node:events");

function run(command, args, options = {}, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { windowsHide: true, ...options });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish({ ok: false, code: -1, stdout, stderr: stderr + "\nTimed out." });
    }, timeoutMs);
    child.stdout?.on("data", (d) => { stdout += d.toString(); });
    child.stderr?.on("data", (d) => { stderr += d.toString(); });
    child.on("error", (err) => finish({ ok: false, code: -1, stdout, stderr: String(err.message || err) }));
    child.on("close", (code) => finish({ ok: code === 0, code, stdout, stderr }));
  });
}

async function findPython() {
  const candidates = process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, prefix] of candidates) {
    const result = await run(cmd, [...prefix, "--version"], {}, 8000);
    if (result.ok) return { cmd, prefix, version: (result.stdout || result.stderr).trim() };
  }
  throw new Error("Python 3.10+ was not found. Install Python, then retry the RONN bridge setup.");
}

class BridgeManager extends EventEmitter {
  constructor({ userData, sourceDir }) {
    super();
    this.userData = userData;
    this.sourceDir = sourceDir;
    this.installDir = path.join(userData, "roblox-bridge");
    this.configPath = process.platform === "win32"
      ? path.join(process.env.LOCALAPPDATA || userData, "RONN", "roblox_bridge.json")
      : path.join(process.env.HOME || userData, ".ronn", "roblox_bridge.json");
    this.child = null;
    this.desiredRunning = false;
    this.stopping = false;
    this.lastExit = null;
    this.lastError = "";
    this.restartTimer = null;
  }

  emitState(type, detail = {}) {
    this.emit("event", { source: "bridge", type, at: Date.now(), ...detail });
  }

  venvPython() {
    return process.platform === "win32"
      ? path.join(this.installDir, ".venv", "Scripts", "python.exe")
      : path.join(this.installDir, ".venv", "bin", "python");
  }

  bridgeFile() {
    return path.join(this.installDir, "bridge.py");
  }

  status() {
    return {
      installed: fs.existsSync(this.bridgeFile()) && fs.existsSync(this.venvPython()),
      configured: fs.existsSync(this.configPath),
      running: Boolean(this.child && this.child.exitCode == null),
      pid: this.child && this.child.exitCode == null ? this.child.pid : null,
      last_exit: this.lastExit,
      last_error: this.lastError,
      install_dir: this.installDir,
    };
  }

  copyBridgeFiles() {
    if (!fs.existsSync(this.sourceDir)) throw new Error("Bundled RONN Roblox bridge files are missing.");
    fs.mkdirSync(this.installDir, { recursive: true });
    for (const name of ["bridge.py", "requirements.txt", "README.md"]) {
      const src = path.join(this.sourceDir, name);
      if (!fs.existsSync(src)) throw new Error("Missing bridge component: " + name);
      fs.copyFileSync(src, path.join(this.installDir, name));
    }
  }

  async install() {
    this.emitState("install-start");
    this.copyBridgeFiles();
    const py = await findPython();
    const venv = await run(py.cmd, [...py.prefix, "-m", "venv", ".venv"], { cwd: this.installDir }, 120000);
    if (!venv.ok) throw new Error(venv.stderr || "Could not create the RONN bridge virtual environment.");
    const python = this.venvPython();
    const pipUpgrade = await run(python, ["-m", "pip", "install", "--upgrade", "pip"], { cwd: this.installDir }, 120000);
    if (!pipUpgrade.ok) throw new Error(pipUpgrade.stderr || "Could not prepare pip.");
    const deps = await run(python, ["-m", "pip", "install", "-r", "requirements.txt"], { cwd: this.installDir }, 180000);
    if (!deps.ok) throw new Error(deps.stderr || "Could not install the RONN bridge dependencies.");
    this.emitState("install-complete", { python: py.version });
    return this.status();
  }

  async ensureInstalled() {
    if (!this.status().installed) await this.install();
  }

  _launch(args) {
    if (this.child && this.child.exitCode == null) return this.status();
    const python = this.venvPython();
    if (!fs.existsSync(python)) throw new Error("RONN Roblox bridge is not installed.");
    this.stopping = false;
    const child = spawn(python, ["bridge.py", ...args], {
      cwd: this.installDir,
      windowsHide: true,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    this.child = child;
    this.emitState("started", { pid: child.pid });
    child.stdout.on("data", (d) => {
      const text = d.toString().trim();
      if (text) this.emitState("log", { text: text.slice(-1000) });
    });
    child.stderr.on("data", (d) => {
      const text = d.toString().trim();
      if (text) {
        this.lastError = text.slice(-1000);
        this.emitState("error-log", { text: this.lastError });
      }
    });
    child.on("error", (err) => {
      this.lastError = String(err.message || err);
      this.emitState("process-error", { error: this.lastError });
    });
    child.on("close", (code) => {
      this.lastExit = { code, at: Date.now() };
      this.child = null;
      this.emitState("stopped", { code });
      if (this.desiredRunning && !this.stopping) {
        clearTimeout(this.restartTimer);
        this.restartTimer = setTimeout(() => {
          try {
            this.emitState("restart");
            this._launch([]);
          } catch (err) {
            this.lastError = String(err.message || err);
            this.emitState("restart-failed", { error: this.lastError });
          }
        }, 2500);
      }
    });
    return this.status();
  }

  async pairAndStart({ server, pairCode, name = "RONN Desktop" }) {
    await this.ensureInstalled();
    if (!/^https:\/\//i.test(String(server || "").trim()) && !/^http:\/\/127\.0\.0\.1(?::\d+)?$/i.test(String(server || "").trim())) {
      throw new Error("RONN Core must use HTTPS, except a local 127.0.0.1 development server.");
    }
    if (!/^[A-Za-z0-9-]{6,32}$/.test(String(pairCode || "").trim())) throw new Error("Invalid pairing code.");
    await this.stop();
    this.desiredRunning = true;
    return this._launch(["--server", String(server).trim(), "--pair", String(pairCode).trim().toUpperCase(), "--name", String(name).slice(0, 80)]);
  }

  async start() {
    await this.ensureInstalled();
    if (!fs.existsSync(this.configPath)) throw new Error("Pair this PC with RONN once before starting the bridge.");
    this.desiredRunning = true;
    return this._launch([]);
  }

  async stop() {
    this.desiredRunning = false;
    this.stopping = true;
    clearTimeout(this.restartTimer);
    if (this.child && this.child.exitCode == null) {
      const child = this.child;
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          try { child.kill(); } catch {}
          resolve();
        }, 3000);
        child.once("close", () => { clearTimeout(timer); resolve(); });
        try { child.kill(); } catch { clearTimeout(timer); resolve(); }
      });
    }
    this.child = null;
    this.stopping = false;
    return this.status();
  }
}

module.exports = { BridgeManager, run };
