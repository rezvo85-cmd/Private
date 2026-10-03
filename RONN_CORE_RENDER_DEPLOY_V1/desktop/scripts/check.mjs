import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const root = path.resolve(import.meta.dirname, "..");
const required = [
  "package.json",
  "index.html",
  "electron/main.cjs",
  "electron/preload.cjs",
  "electron/bridge-manager.cjs",
  "electron/toolchain.cjs",
  "electron/checkpoints.cjs",
  "electron/session-store.cjs",
  "electron/diagnostics.cjs",
  "THIRD_PARTY_NOTICES.md",
  "src/main.jsx",
  "src/App.jsx",
  "src/api.js",
  "src/styles.css",
];
for (const file of required) {
  if (!fs.existsSync(path.join(root, file))) throw new Error("Missing desktop file: " + file);
}
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
for (const dep of ["react", "react-dom", "electron-updater"]) {
  if (!pkg.dependencies?.[dep]) throw new Error("Missing dependency: " + dep);
}
for (const dep of ["electron", "electron-builder", "vite", "@vitejs/plugin-react"]) {
  if (!pkg.devDependencies?.[dep]) throw new Error("Missing dev dependency: " + dep);
}
const main = fs.readFileSync(path.join(root, "electron/main.cjs"), "utf8");
if (main.includes("webSecurity: false")) throw new Error("Desktop must not disable Chromium web security.");
if (!main.includes('contextIsolation: true') || !main.includes('nodeIntegration: false')) throw new Error("Electron isolation boundary missing.");
const toolchain = fs.readFileSync(path.join(root, "electron/toolchain.cjs"), "utf8");
if (!toolchain.includes("sha256") || !toolchain.includes("f9ba1704014ff67")) throw new Error("Pinned Rokit checksum verification missing.");
const sessions = fs.readFileSync(path.join(root, "electron/session-store.cjs"), "utf8");
if (!sessions.includes("interruptRunning") || !sessions.includes("automatic") && !sessions.includes("interrupted")) throw new Error("Recoverable Studio session support missing.");
const diagnostics = fs.readFileSync(path.join(root, "electron/diagnostics.cjs"), "utf8");
if (!diagnostics.includes("[redacted]") || !diagnostics.includes("MAX_ENTRIES")) throw new Error("Bounded scrubbed diagnostics support missing.");
const notices = fs.readFileSync(path.join(root, "THIRD_PARTY_NOTICES.md"), "utf8");
if (!notices.includes("BloxBot") || !notices.includes("MIT License")) throw new Error("BloxBot MIT attribution missing.");

const { scrub } = require(path.join(root, "electron/diagnostics.cjs"));
const scrubbed = scrub("C:\\Users\\Jane\\game token=github_pat_123456789012345678901234567890 jane@example.com", "C:\\Users\\Jane", "Jane", 1200);
if (scrubbed.includes("github_pat_") || scrubbed.includes("jane@example.com") || scrubbed.includes("C:\\Users\\Jane")) {
  throw new Error("Diagnostics secret/path scrubbing failed.");
}

const { SessionStore } = require(path.join(root, "electron/session-store.cjs"));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "ronn-session-check-"));
try {
  const store = new SessionStore(temp);
  const row = store.create({ task: "Fix RightDash", selected_path: "game.Workspace.R6" });
  store.interruptRunning();
  const recovered = store.get(row.id);
  if (!recovered || recovered.state !== "interrupted") throw new Error("Interrupted Studio session recovery failed.");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}

console.log("RONN Desktop static checks: PASS");
