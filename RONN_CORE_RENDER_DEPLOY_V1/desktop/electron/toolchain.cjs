const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const https = require("node:https");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const extract = require("extract-zip");

const ROKIT_VERSION = "1.2.0";
const ROKIT = {
  x64: {
    url: "https://github.com/rojo-rbx/rokit/releases/download/v1.2.0/rokit-1.2.0-windows-x86_64.zip",
    sha256: "f9ba1704014ff67d51e8005f605955c7c26d2429a5312a9419dc477fc310e96d",
  },
  arm64: {
    url: "https://github.com/rojo-rbx/rokit/releases/download/v1.2.0/rokit-1.2.0-windows-aarch64.zip",
    sha256: "aff0e76e304fdc938cffa5b7ee1e183a052acac541868b4271192f20c734282a",
  },
};

function run(cmd, args, cwd, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd, windowsHide: true });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve({ ok: false, code: -1, stdout, stderr: stderr + "\nTimed out." });
    }, timeoutMs);
    child.stdout?.on("data", (d) => { stdout += d.toString(); });
    child.stderr?.on("data", (d) => { stderr += d.toString(); });
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

function download(url, destination, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 6) return reject(new Error("Too many download redirects."));
    const req = https.get(url, { headers: { "User-Agent": "RONN-Desktop/1.0" } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return resolve(download(new URL(res.headers.location, url).toString(), destination, redirects + 1));
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error("Download failed with HTTP " + res.statusCode));
      }
      const out = fs.createWriteStream(destination);
      res.pipe(out);
      out.on("finish", () => out.close(resolve));
      out.on("error", reject);
    });
    req.on("error", reject);
  });
}

function sha256(file) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(file));
  return hash.digest("hex");
}

function findFile(root, filename) {
  if (!fs.existsSync(root)) return null;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isFile() && entry.name.toLowerCase() === filename.toLowerCase()) return full;
    if (entry.isDirectory()) {
      const hit = findFile(full, filename);
      if (hit) return hit;
    }
  }
  return null;
}

class ToolchainManager {
  constructor({ userData, manifestSource }) {
    this.root = path.join(userData, "roblox-toolchain");
    this.manifestSource = manifestSource;
    this.rokitExe = path.join(this.root, "bin", "rokit.exe");
    this.rojoProcess = null;
  }

  knownBin(name) {
    if (process.platform === "win32") {
      return path.join(os.homedir(), ".rokit", "bin", name + ".exe");
    }
    return path.join(os.homedir(), ".rokit", "bin", name);
  }

  async version(binary) {
    if (!binary || !fs.existsSync(binary)) return null;
    const result = await run(binary, ["--version"], this.root, 10000);
    return result.ok ? (result.stdout || result.stderr).trim() : null;
  }

  async status() {
    const rojo = this.knownBin("rojo");
    const wally = this.knownBin("wally");
    return {
      rokit: await this.version(this.rokitExe),
      rojo: await this.version(rojo),
      wally: await this.version(wally),
      rojo_plugin_ready: Boolean(await this.version(rojo)),
      rojo_server_running: Boolean(this.rojoProcess && this.rojoProcess.exitCode == null),
      manifest: path.join(this.root, "rokit.toml"),
    };
  }

  async install() {
    if (process.platform !== "win32") {
      throw new Error("Automatic Rokit bootstrap is currently enabled on Windows. Install Rokit manually on this platform, then use rokit install.");
    }
    fs.mkdirSync(path.join(this.root, "bin"), { recursive: true });
    fs.copyFileSync(this.manifestSource, path.join(this.root, "rokit.toml"));
    if (!fs.existsSync(this.rokitExe)) {
      const spec = ROKIT[process.arch === "arm64" ? "arm64" : "x64"];
      const zip = path.join(this.root, "rokit.zip");
      const extractDir = path.join(this.root, "rokit-download");
      fs.rmSync(extractDir, { recursive: true, force: true });
      await download(spec.url, zip);
      const digest = sha256(zip);
      if (digest !== spec.sha256) {
        fs.rmSync(zip, { force: true });
        throw new Error("Rokit download checksum did not match the pinned official release.");
      }
      await extract(zip, { dir: extractDir });
      const downloaded = findFile(extractDir, "rokit.exe");
      if (!downloaded) throw new Error("The verified Rokit archive did not contain rokit.exe.");
      fs.copyFileSync(downloaded, this.rokitExe);
      fs.rmSync(zip, { force: true });
      fs.rmSync(extractDir, { recursive: true, force: true });
    }
    const selfInstall = await run(this.rokitExe, ["self-install"], this.root, 60000);
    if (!selfInstall.ok && !/already/i.test(selfInstall.stderr + selfInstall.stdout)) {
      throw new Error(selfInstall.stderr || "Rokit self-install failed.");
    }
    const install = await run(this.rokitExe, ["install"], this.root, 180000);
    if (!install.ok) throw new Error(install.stderr || "Rokit could not install the pinned Roblox tools.");
    return this.status();
  }

  async installRojoPlugin() {
    const rojo = this.knownBin("rojo");
    if (!fs.existsSync(rojo)) throw new Error("Install the RONN Roblox toolchain first.");
    const result = await run(rojo, ["plugin", "install"], this.root, 60000);
    if (!result.ok) throw new Error(result.stderr || "Rojo Studio plugin installation failed.");
    return { ok: true, output: (result.stdout || result.stderr).trim() };
  }

  async startRojo(workspace) {
    const rojo = this.knownBin("rojo");
    if (!fs.existsSync(rojo)) throw new Error("Install the RONN Roblox toolchain first.");
    if (!workspace || !fs.existsSync(workspace)) throw new Error("Choose a valid Roblox workspace.");
    if (this.rojoProcess && this.rojoProcess.exitCode == null) return { ok: true, already_running: true };
    this.rojoProcess = spawn(rojo, ["serve"], { cwd: workspace, windowsHide: true });
    this.rojoProcess.on("close", () => { this.rojoProcess = null; });
    return { ok: true, pid: this.rojoProcess.pid };
  }

  async stopRojo() {
    if (this.rojoProcess && this.rojoProcess.exitCode == null) {
      try { this.rojoProcess.kill(); } catch {}
    }
    this.rojoProcess = null;
    return { ok: true };
  }
}

module.exports = { ToolchainManager, ROKIT_VERSION };
