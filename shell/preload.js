/* Мост окна и оболочки: порт и секрет ядра, уведомления, горячие клавиши, трей. */
const { contextBridge, ipcRenderer } = require("electron");

const arg = (name) => {
  const a = process.argv.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : "";
};

contextBridge.exposeInMainWorld("jarvisShell", {
  port: Number(arg("jarvis-port")),
  secret: arg("jarvis-secret"),
  version: arg("jarvis-version"),
  platform: process.platform,
  notify: (title, body) => ipcRenderer.send("notify", title, body),
  setHotkey: (accel) => ipcRenderer.invoke("set-hotkey", accel),
  setAutostart: (on) => ipcRenderer.invoke("set-autostart", on),
  openExternal: (url) => ipcRenderer.send("open-external", url),
  saveFile: (name, data) => ipcRenderer.invoke("save-file", name, data),
  onHotkey: (cb) => ipcRenderer.on("hotkey", () => cb()),
  onTray: (cb) => ipcRenderer.on("tray", (_e, action) => cb(action)),
  showWindow: () => ipcRenderer.send("show-window"),
  quit: () => ipcRenderer.send("quit"),
  coreStatus: () => ipcRenderer.invoke("core-status"),
});
