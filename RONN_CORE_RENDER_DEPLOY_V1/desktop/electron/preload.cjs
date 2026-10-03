const { contextBridge, ipcRenderer } = require("electron");

const invoke = (channel, payload) => ipcRenderer.invoke(channel, payload);

contextBridge.exposeInMainWorld("ronnDesktop", {
  bridge: {
    status: () => invoke("bridge:status"),
    install: () => invoke("bridge:install"),
    pairAndStart: (payload) => invoke("bridge:pair-start", payload),
    start: () => invoke("bridge:start"),
    stop: () => invoke("bridge:stop"),
  },
  toolchain: {
    status: () => invoke("toolchain:status"),
    install: () => invoke("toolchain:install"),
    installRojoPlugin: () => invoke("toolchain:rojo-plugin"),
    startRojo: (workspace) => invoke("toolchain:rojo-start", { workspace }),
    stopRojo: () => invoke("toolchain:rojo-stop"),
  },
  workspace: {
    choose: () => invoke("workspace:choose"),
    current: () => invoke("workspace:current"),
    set: (workspace) => invoke("workspace:set", { workspace }),
    checkpoint: (label) => invoke("workspace:checkpoint", { label }),
    checkpoints: () => invoke("workspace:checkpoints"),
    restore: (sha) => invoke("workspace:restore", { sha }),
  },
  updater: {
    status: () => invoke("updater:status"),
    check: () => invoke("updater:check"),
    install: () => invoke("updater:install"),
  },
  onEvent: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("ronn:event", listener);
    return () => ipcRenderer.removeListener("ronn:event", listener);
  },
});
