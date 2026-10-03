import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const required = [
  "package.json",
  "index.html",
  "electron/main.cjs",
  "electron/preload.cjs",
  "electron/bridge-manager.cjs",
  "electron/toolchain.cjs",
  "electron/checkpoints.cjs",
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
console.log("RONN Desktop static checks: PASS");
