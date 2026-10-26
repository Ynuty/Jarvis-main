/* ============================================================
   Сборка приложения: ждём ядро → вход → мастер первого запуска
   → HUD и экраны. HUD живёт всё время (реактор, слух, таймеры),
   остальные экраны строятся при переходе.
   ============================================================ */

import "@fontsource/jura/400.css";
import "@fontsource/jura/500.css";
import "@fontsource/jura/600.css";
import "@fontsource/jura/700.css";
import "@fontsource/jetbrains-mono/300.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/600.css";
import "./styles/hud.css";
import "./styles/app.css";

import { api, getToken, link, setToken, shell, waitCore } from "./api";
import { app, applyAccent } from "./state";
import { h, hhmmss, toast } from "./ui";
import { cartView } from "./screens/cart";
import { daySheet } from "./screens/daysheet";
import { gate, type LoginResult } from "./screens/gate";
import { journalView } from "./screens/journal";
import { mailView } from "./screens/mail";
import { autoListen, bootGreeting, mainView, stateChip, stopAll, wire } from "./screens/main";
import { memoryView } from "./screens/memory";
import { profileView } from "./screens/profile";
import { settingsView } from "./screens/settings";
import { wizard } from "./screens/wizard";

const root = document.getElementById("root")!;
const ROUTES: [string, string][] = [
  ["hud", "Джарвис"], ["profile", "Профиль"], ["memory", "Память"], ["cart", "Корзина"],
  ["mail", "Почта"], ["journal", "Журнал"], ["settings", "Настройки"],
];
let wired = false;

async function start(): Promise<void> {
  root.replaceChildren(h("div", { class: "gate" }, h("div", { class: "gate__inner" },
    h("h1", { class: "gate__title" }, "J.A.R.V.I.S."), h("p", { class: "gate__desc" }, "Запуск ядра…"))));
  try {
    await waitCore(shell ? 240 : 20);
  } catch {
    const st = shell ? await shell.coreStatus() : null;
    root.replaceChildren(h("div", { class: "gate" }, h("div", { class: "gate__inner" },
      h("h1", { class: "gate__title" }, "J.A.R.V.I.S."),
      h("p", { class: "error" }, "Ядро не запустилось."),
      st ? h("pre", { class: "card muted mono", style: { textAlign: "left", whiteSpace: "pre-wrap", maxHeight: "40vh", overflow: "auto" } },
        `Ядро: ${st.core}\nOllama: ${st.ollama}\n\n${st.log}`) : h("p", { class: "muted" }, "Запустите ядро: python -m jarvis"),
      h("button", { class: "btn", type: "button", on: { click: () => location.reload() } }, "Повторить"))));
    return;
  }
  showGate();
}

function showGate(): void {
  link.close();
  root.replaceChildren(gate(onLogin));
}

async function onLogin(r: LoginResult): Promise<void> {
  app.profile = r.profile;
  const { settings } = await api("/api/settings");
  app.settings = settings;
  applyAccent(settings.accent);
  if (r.first_run) {
    root.replaceChildren(wizard(() => void enter()));
    return;
  }
  void enter();
}

async function enter(): Promise<void> {
  const { settings } = await api("/api/settings");
  app.settings = settings;
  if (shell && settings.hotkey_global) void shell.setHotkey(settings.hotkey_global);

  const modeChip = h("span", { class: "chip chip--ghost" }, "по обращению");
  const clock = h("span", { class: "clock" }, "--:--:--");
  const nav = h("nav", { class: "nav", "aria-label": "Разделы" }, ROUTES.map(([id, title]) =>
    h("button", { class: "tab", type: "button", "data-route": id, on: { click: () => void go(id) } }, title)));
  const hud = mainView();
  const page = h("div", { class: "page", style: { display: "none" } });
  const [tongue, sheet] = daySheet();

  const frame = h("div", { class: "frame" },
    h("header", { class: "bar", style: { position: "relative" } },
      h("div", { class: "mark" }, h("span", { class: "mark__name" }, "J·A·R·V·I·S"),
        h("span", { class: "mark__exp" }, app.profile?.name ?? "")),
      h("div", { class: "bar__mid" }, stateChip(), modeChip),
      h("div", { class: "bar__right" },
        h("span", { class: "local", title: "Речь, нейросеть и данные — на этом компьютере. В сеть — только по вашей просьбе." },
          h("i", { class: "dot ok" }), "Локально"),
        clock,
        h("button", { class: "iconbtn", type: "button", title: "Полный экран", on: { click: () => {
          if (document.fullscreenElement) void document.exitFullscreen(); else void document.documentElement.requestFullscreen();
        } } }, "⛶")),
      nav,
      tongue),
    hud, page);
  if (shell?.platform === "win32") document.body.classList.add("shell-win");
  root.replaceChildren(frame, sheet);

  app.on("clock", (t: string) => { clock.textContent = t; });
  app.on("mode", (m: string) => { modeChip.textContent = { wake: "по обращению", open: "без обращения", ptt: "по кнопке" }[m] || m; });
  clock.textContent = hhmmss();

  async function go(id: string): Promise<void> {
    app.route = id;
    nav.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-current", (t as HTMLElement).dataset.route === id ? "page" : "false"));
    const isHud = id === "hud";
    (hud as HTMLElement).style.display = isHud ? "contents" : "none";
    page.style.display = isHud ? "none" : "";
    if (isHud) return;
    page.replaceChildren(h("p", { class: "muted" }, "Загрузка…"));
    try {
      const view = id === "profile" ? await profileView(logout)
        : id === "memory" ? await memoryView()
        : id === "cart" ? await cartView()
        : id === "mail" ? await mailView()
        : id === "journal" ? await journalView()
        : await settingsView(() => root.replaceChildren(wizard(() => void enter())));
      page.replaceChildren(view);
    } catch (e: any) {
      page.replaceChildren(h("p", { class: "error" }, e.message));
    }
  }

  if (!wired) { wire(); wired = true; }
  link.on("settings", (m) => { app.settings = m.settings; applyAccent(m.settings.accent); });
  link.connect();
  shell?.onTray((action) => {
    if (action === "stop") stopAll();
    if (action.startsWith("route:")) void go(action.slice(6));
  });
  void go("hud");
  bootGreeting();
  link.on("hello", () => autoListen());
}

function logout(): void {
  setToken("");
  app.profile = null;
  link.close();
  showGate();
}

// токен пропал (ядро перезапустилось) — в том числе посреди мастера первого запуска
link.on("auth_lost", () => {
  if (!getToken()) return;
  toast("Ядро перезапустилось — войдите снова.", true);
  logout();
});

window.addEventListener("unhandledrejection", (e) => {
  const msg = (e.reason && e.reason.message) || String(e.reason);
  if (!/AbortError|Failed to fetch/.test(msg)) toast(msg, true);
});

void start();
