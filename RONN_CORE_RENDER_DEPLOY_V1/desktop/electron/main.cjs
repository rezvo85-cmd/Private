const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { autoUpdater } = require("electron-updater");
const { BridgeManager } = require("./bridge-manager.cjs");
const { ToolchainManager } = require("./toolchain.cjs");
const checkpoints = require("./checkpoints.cjs");

let mainWindow = null;
let bridge = null;
let toolchain = null;
let updaterState = { status: "idle", version: app.getVersion(), progress: 0 };

function sendEvent(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("ronn:event", payload);
}

function prefsPath() {
  return path.join(app.getPath("userData"), "desktop.json");
}
function readPrefs() {
  try { return JSON.parse(fs.readFileSync(prefsPath(), "utf8")); } catch { return {}; }
}
function writePrefs(next) {
  fs.mkdirSync(path.dirname(prefsPath()), { recursive: true });
  fs.writeFileSync(prefsPath(), JSON.stringify(next, null, 2), "utf8");
}
function setWorkspace(workspace) {
  const prefs = readPrefs();
  prefs.workspace = workspace || "";
  writePrefs(prefs);
  return prefs.workspace;
}
function getWorkspace() {
  return String(readPrefs().workspace || "");
}

function resourcePath(name) {
  if (app.isPackaged) return path.join(process.resourcesPath, name);
  return path.resolve(__dirname, "..", "..", name);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1050,
    minHeight: 680,
    backgroundColor: "#090a0e",
    title: "RONN · Roblox Studio",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  const devUrl = process.env.RONN_DESKTOP_DEV_URL;
  if (devUrl) mainWindow.loadURL(devUrl);
  else mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
}

function setupUpdater() {
  if (!app.isPackaged) {
    updaterState = { ...updaterState, status: "development" };
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on("checking-for-update", () => { updaterState = { ...updaterState, status: "checking" }; sendEvent({ source: "updater", ...updaterState }); });
  autoUpdater.on("update-available", (info) => { updaterState = { ...updaterState, status: "available", available: info.version }; sendEvent({ source: "updater", ...updaterState }); });
  autoUpdater.on("update-not-available", () => { updaterState = { ...updaterState, status: "current" }; sendEvent({ source: "updater", ...updaterState }); });
  autoUpdater.on("download-progress", (p) => { updaterState = { ...updaterState, status: "downloading", progress: Math.round(p.percent || 0) }; sendEvent({ source: "updater", ...updaterState }); });
  autoUpdater.on("update-downloaded", (info) => { updaterState = { ...updaterState, status: "ready", available: info.version, progress: 100 }; sendEvent({ source: "updater", ...updaterState }); });
  autoUpdater.on("error", (err) => { updaterState = { ...updaterState, status: "error", error: String(err.message || err).slice(0, 300) }; sendEvent({ source: "updater", ...updaterState }); });
  setTimeout(() => autoUpdater.checkForUpdates().catch(() => {}), 8000);
}

function registerIpc() {
  ipcMain.handle("core:request", async (_event, payload) => {
    const base = new URL(String(payload?.baseUrl || "").trim());
    const isLocal = ["127.0.0.1", "localhost"].includes(base.hostname);
    if (base.protocol !== "https:" && !(isLocal && base.protocol === "http:")) {
      throw new Error("RONN Core must use HTTPS, except localhost development.");
    }
    const endpoint = String(payload?.path || "");
    if (!endpoint.startsWith("/api/") || endpoint.includes("\\") || endpoint.length > 500) {
      throw new Error("Invalid RONN Core API path.");
    }
    const method = String(payload?.method || "GET").toUpperCase();
    if (!["GET", "POST", "PATCH", "DELETE"].includes(method)) throw new Error("Unsupported HTTP method.");
    const incoming = payload?.headers && typeof payload.headers === "object" ? payload.headers : {};
    const headers = {};
    for (const key of ["X-RONN-Client", "X-RONN-Device", "X-RONN-Account", "Content-Type"]) {
      const value = incoming[key];
      if (value != null) headers[key] = String(value).slice(0, 500);
    }
    const options = { method, headers, redirect: "error" };
    if (method !== "GET" && payload?.body != null) {
      const body = typeof payload.body === "string" ? payload.body : JSON.stringify(payload.body);
      if (Buffer.byteLength(body, "utf8") > 2 * 1024 * 1024) throw new Error("RONN request body is too large.");
      options.body = body;
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
    }
    const response = await fetch(new URL(endpoint, base), options);
    const textBody = await response.text();
    if (Buffer.byteLength(textBody, "utf8") > 4 * 1024 * 1024) throw new Error("RONN Core response exceeded the desktop safety limit.");
    let data = textBody;
    try { data = textBody ? JSON.parse(textBody) : {}; } catch {}
    return { ok: response.ok, status: response.status, data };
  });

  ipcMain.handle("bridge:status", () => bridge.status());
  ipcMain.handle("bridge:install", () => bridge.install());
  ipcMain.handle("bridge:pair-start", (_e, payload) => bridge.pairAndStart(payload || {}));
  ipcMain.handle("bridge:start", () => bridge.start());
  ipcMain.handle("bridge:stop", () => bridge.stop());

  ipcMain.handle("toolchain:status", () => toolchain.status());
  ipcMain.handle("toolchain:install", () => toolchain.install());
  ipcMain.handle("toolchain:rojo-plugin", () => toolchain.installRojoPlugin());
  ipcMain.handle("toolchain:rojo-start", (_e, payload) => toolchain.startRojo(String(payload?.workspace || getWorkspace())));
  ipcMain.handle("toolchain:rojo-stop", () => toolchain.stopRojo());

  ipcMain.handle("workspace:choose", async () => {
    const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory", "createDirectory"] });
    if (result.canceled || !result.filePaths[0]) return { workspace: getWorkspace(), canceled: true };
    return { workspace: setWorkspace(result.filePaths[0]), canceled: false };
  });
  ipcMain.handle("workspace:current", () => ({ workspace: getWorkspace() }));
  ipcMain.handle("workspace:set", (_e, payload) => ({ workspace: setWorkspace(String(payload?.workspace || "")) }));
  ipcMain.handle("workspace:checkpoint", (_e, payload) => checkpoints.checkpoint(getWorkspace(), payload?.label));
  ipcMain.handle("workspace:checkpoints", () => checkpoints.list(getWorkspace()));
  ipcMain.handle("workspace:restore", (_e, payload) => checkpoints.restore(getWorkspace(), payload?.sha));

  ipcMain.handle("updater:status", () => updaterState);
  ipcMain.handle("updater:check", async () => {
    if (!app.isPackaged) return updaterState;
    await autoUpdater.checkForUpdates();
    return updaterState;
  });
  ipcMain.handle("updater:install", () => {
    if (updaterState.status === "ready") autoUpdater.quitAndInstall(false, true);
    return updaterState;
  });
}

app.whenReady().then(async () => {
  createWindow();
  bridge = new BridgeManager({ userData: app.getPath("userData"), sourceDir: resourcePath("roblox_bridge") });
  toolchain = new ToolchainManager({
    userData: app.getPath("userData"),
    manifestSource: path.join(resourcePath("roblox_toolchain"), "rokit.toml"),
  });
  bridge.on("event", sendEvent);
  registerIpc();
  setupUpdater();
  if (bridge.status().installed && bridge.status().configured) {
    bridge.start().catch((err) => sendEvent({ source: "bridge", type: "autostart-failed", error: String(err.message || err) }));
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", () => {
  bridge?.stop().catch(() => {});
  toolchain?.stopRojo().catch(() => {});
});
