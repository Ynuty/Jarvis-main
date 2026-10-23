/* ============================================================
   Оболочка J.A.R.V.I.S. (Electron).
   - поднимает Ollama (если не запущена) и Python-ядро, показывает
     ошибки, если они не стартовали; перезапускает упавшее ядро;
   - общий секрет ядра и окна: чужие страницы не дотянутся до API;
   - трей, глобальная горячая клавиша, автозапуск, уведомления;
   - закрытие окна сворачивает в трей, выход — из меню трея.
   ============================================================ */

const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, Notification, nativeImage, shell, dialog, session } = require("electron");
const { spawn, execFile } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const net = require("net");
const path = require("path");
const http = require("http");

const DEV = process.env.JARVIS_DEV === "1" || !app.isPackaged;
const ROOT = path.resolve(__dirname, "..");
const SECRET = crypto.randomBytes(24).toString("hex");
const ICON = path.join(__dirname, "icon.png");

let win = null;
let tray = null;
let core = null;
let corePort = 0;
let coreState = "не запущено";
let ollamaState = "не проверена";
let coreLog = [];
let restarts = 0;
let quitting = false;
let hotkey = "";

// Второй запуск только показывает уже открытое окно и сразу выходит (ядро не трогает).
const firstInstance = app.requestSingleInstanceLock();
if (!firstInstance) app.exit(0);
app.on("second-instance", () => showWindow());

// ---------- утилиты ----------

function log(line) {
  coreLog.push(line);
  if (coreLog.length > 200) coreLog = coreLog.slice(-200);
}

function freePort(start) {
  return new Promise((resolve) => {
    const tryPort = (p) => {
      const srv = net.createServer();
      srv.once("error", () => tryPort(p + 1));
      srv.once("listening", () => srv.close(() => resolve(p)));
      srv.listen(p, "127.0.0.1");
    };
    tryPort(start);
  });
}

function httpOk(url, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout }, (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- Ollama ----------

function findOllama() {
  const cands = [
    path.join(process.env.LOCALAPPDATA || "", "Programs", "Ollama", "ollama.exe"),
    path.join(process.env.ProgramFiles || "", "Ollama", "ollama.exe"),
    "/usr/local/bin/ollama", "/opt/homebrew/bin/ollama", "/usr/bin/ollama",
  ];
  return cands.find((p) => p && fs.existsSync(p)) || "ollama";
}

async function ensureOllama() {
  if (await httpOk("http://127.0.0.1:11434/api/version")) { ollamaState = "работает"; return; }
  ollamaState = "запускаю…";
  try {
    const p = spawn(findOllama(), ["serve"], { detached: true, stdio: "ignore", windowsHide: true });
    p.on("error", (e) => { ollamaState = "не найдена: установите с ollama.com (" + e.code + ")"; });
    p.unref();
  } catch (e) {
    ollamaState = "не удалось запустить: " + e.message;
    return;
  }
  for (let i = 0; i < 40; i++) {
    if (await httpOk("http://127.0.0.1:11434/api/version")) { ollamaState = "работает"; return; }
    await sleep(500);
  }
  if (ollamaState === "запускаю…") ollamaState = "не ответила за 20 секунд";
}

// ---------- ядро ----------

function coreCommand() {
  if (!DEV) {
    const exe = path.join(process.resourcesPath, "core", process.platform === "win32" ? "jarvis-core.exe" : "jarvis-core");
    return { cmd: exe, args: [] };
  }
  const py = process.platform === "win32"
    ? path.join(ROOT, "core", ".venv", "Scripts", "python.exe")
    : path.join(ROOT, "core", ".venv", "bin", "python");
  return { cmd: py, args: ["-m", "jarvis"] };
}

async function startCore() {
  corePort = corePort || await freePort(8777);
  const { cmd, args } = coreCommand();
  coreState = "запускается";
  log(`> ${cmd} ${args.join(" ")} --port ${corePort}`);
  const env = { ...process.env, JARVIS_SECRET: SECRET, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" };
  if (process.env.JARVIS_HOME) env.JARVIS_HOME = process.env.JARVIS_HOME;
  try {
    core = spawn(cmd, [...args, "--port", String(corePort)], { cwd: DEV ? path.join(ROOT, "core") : path.dirname(cmd), env, windowsHide: true });
  } catch (e) {
    coreState = "не запустилось: " + e.message;
    return;
  }
  core.stdout.on("data", (d) => {
    const s = d.toString("utf8");
    s.split(/\r?\n/).filter(Boolean).forEach(log);
    if (s.includes("JARVIS_CORE_READY")) { coreState = "работает"; restarts = 0; }
  });
  core.stderr.on("data", (d) => d.toString("utf8").split(/\r?\n/).filter(Boolean).forEach(log));
  core.on("error", (e) => { coreState = "ошибка запуска: " + e.message; log(coreState); });
  core.on("exit", async (code) => {
    log(`ядро завершилось с кодом ${code}`);
    core = null;
    if (quitting) return;
    coreState = `упало (код ${code})`;
    if (restarts++ < 3) {
      notify("Джарвис", "Ядро перезапускается…");
      await sleep(1500);
      void startCore();
    } else {
      coreState = "упало 3 раза подряд — смотрите журнал ядра";
      win?.webContents.reload();
    }
  });
}

function stopCore() {
  if (!core) return;
  const pid = core.pid;
  if (process.platform === "win32") execFile("taskkill", ["/pid", String(pid), "/T", "/F"], () => {});
  else core.kill("SIGTERM");
  core = null;
}

// ---------- окно ----------

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 720, minHeight: 520,
    backgroundColor: "#04080d",
    title: "J.A.R.V.I.S.",
    icon: ICON,
    show: false,
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#04080d", symbolColor: "#5ad9ff", height: 34 },
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,      // слух и таймеры работают и в свёрнутом окне
      additionalArguments: [`--jarvis-port=${corePort}`, `--jarvis-secret=${SECRET}`, `--jarvis-version=${app.getVersion()}`],
    },
  });
  win.once("ready-to-show", () => win.show());
  if (DEV && process.env.JARVIS_VITE) win.loadURL(process.env.JARVIS_VITE);
  else win.loadFile(DEV ? path.join(ROOT, "app", "dist", "index.html") : path.join(process.resourcesPath, "app", "index.html"));

  // никаких переходов и всплывающих окон внутри приложения
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url)) shell.openExternal(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, url) => { if (!url.startsWith("file:") && !url.startsWith(process.env.JARVIS_VITE || "~")) e.preventDefault(); });

  win.on("close", (e) => {
    if (quitting) return;
    e.preventDefault();
    win.hide();
    if (!app._trayHinted) {
      app._trayHinted = true;
      notify("Джарвис работает в трее", "Таймеры и слух активны. Выход — через меню значка в трее.");
    }
  });
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function notify(title, body) {
  if (Notification.isSupported()) new Notification({ title, body, icon: ICON, silent: false }).show();
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(ICON).resize({ width: 16, height: 16 }));
  tray.setToolTip("J.A.R.V.I.S.");
  const send = (a) => { showWindow(); win?.webContents.send("tray", a); };
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Показать", click: showWindow },
    { label: "Слушать", click: () => { showWindow(); win?.webContents.send("hotkey"); } },
    { label: "Стоп", click: () => win?.webContents.send("tray", "stop") },
    { type: "separator" },
    { label: "Журнал", click: () => send("route:journal") },
    { label: "Настройки", click: () => send("route:settings") },
    { type: "separator" },
    { label: "Выход", click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on("click", showWindow);
}

function setHotkey(accel) {
  if (hotkey) globalShortcut.unregister(hotkey);
  hotkey = "";
  if (!accel) return true;
  try {
    const ok = globalShortcut.register(accel, () => { showWindow(); win?.webContents.send("hotkey"); });
    if (ok) hotkey = accel;
    return ok;
  } catch {
    return false;
  }
}

// ---------- IPC ----------

ipcMain.on("notify", (_e, title, body) => notify(String(title), String(body)));
ipcMain.handle("set-hotkey", (_e, accel) => setHotkey(String(accel || "")));
ipcMain.handle("set-autostart", (_e, on) => app.setLoginItemSettings({ openAtLogin: !!on, args: ["--hidden"] }));
ipcMain.on("open-external", (_e, url) => { if (/^https?:\/\//.test(url)) shell.openExternal(url); });
ipcMain.on("show-window", showWindow);
ipcMain.on("quit", () => { quitting = true; app.quit(); });
ipcMain.handle("core-status", () => ({ core: coreState, ollama: ollamaState, log: coreLog.slice(-60).join("\n") }));
ipcMain.handle("save-file", async (_e, name, data) => {
  const r = await dialog.showSaveDialog(win, { defaultPath: name });
  if (r.canceled || !r.filePath) return false;
  fs.writeFileSync(r.filePath, Buffer.from(data));
  return true;
});

// ---------- жизненный цикл ----------

app.whenReady().then(async () => {
  if (!firstInstance) return;
  app.setAppUserModelId("local.jarvis.assistant");
  // микрофон — только нашему окну; остальные разрешения запрещены
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb) => cb(perm === "media" || perm === "notifications"));
  corePort = await freePort(8777);
  createTray();
  void ensureOllama();
  await startCore();
  createWindow();
  if (process.argv.includes("--hidden")) win.once("ready-to-show", () => win.hide());
});

app.on("before-quit", () => { quitting = true; globalShortcut.unregisterAll(); stopCore(); });
app.on("window-all-closed", () => { /* живём в трее */ });
