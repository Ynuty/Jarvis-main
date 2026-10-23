/* ============================================================
   Главный экран: реактор с кольцом дня, телеметрия, таймеры,
   журнал диалога, строка ввода. Голос и команды идут в ядро
   по WebSocket; здесь — только отображение и микрофон.
   ============================================================ */

import { link, shell } from "../api";
import * as AudioKit from "../audio";
import * as HUD from "../hud";
import { app } from "../state";
import { clockFromSec, h, hhmmss, toast } from "../ui";
import { toggleDaySheet } from "./daysheet";

const CHIP: Record<string, string> = {
  idle: "ожидание", listen: "слушаю", think: "думаю", speak: "ответ", error: "сбой", sleep: "сон",
  boot: "загрузка", confirm: "подтверждение",
};

let el: Record<string, HTMLElement> = {};
let micWanted = false;
let startedAt = Date.now();
let heard = 0, done = 0;
let confirmCard: HTMLElement | null = null;

export function mainView(): HTMLElement {
  const canvas = h("canvas", { class: "core__canvas", id: "reactor", title: "Нажмите — слушать (пробел)" });
  el = {
    stateChip: h("span", { class: "chip bracket", "data-state": "idle" }, "ожидание"),
    tMic: h("dd", null, "—"), tStt: h("dd", null, "—"), tTts: h("dd", null, "—"), tLlm: h("dd", null, "—"),
    tHeard: h("dd", null, "0"), tDone: h("dd", null, "0"), tUp: h("dd", null, "00:00:00"), tLat: h("dd", null, "—"),
    level: h("i", { class: "meter__fill" }),
    timers: h("ul", { class: "timers__list" }, h("li", { class: "timers__empty" }, "нет активных")),
    caption: h("p", { class: "core__caption" }, "Скажите «Джарвис»"),
    heard: h("p", { class: "core__heard", "aria-live": "polite" }),
    log: h("ol", { class: "log", "aria-live": "polite" }),
    micBtn: h("button", { class: "micbtn", type: "button", "aria-pressed": "false", on: { click: toggleMic } },
      h("span", { class: "micbtn__dot" }), h("span", { id: "micText" }, "Слушать")),
    ask: h("input", { class: "ask__input", type: "text", placeholder: "Или напишите команду…", "aria-label": "Команда" }),
  };
  canvas.addEventListener("click", (e) => {
    const r = canvas.getBoundingClientRect();
    if (HUD.hitCore(e.clientX - r.left, e.clientY - r.top)) toggleMic();
  });

  const row = (label: string, dd: HTMLElement) => h("div", { class: "tele__row" }, h("dt", null, label), dd);
  const view = h("div", { class: "grid" },
    h("aside", { class: "panel bracket panel--left" },
      h("h2", { class: "panel__title" }, "Система"),
      h("dl", { class: "tele" },
        row("Микрофон", el.tMic), row("Распознавание", el.tStt), row("Голос", el.tTts), row("Нейросеть", el.tLlm),
        row("Реплик принято", el.tHeard), row("Команд выполнено", el.tDone), row("Задержка", el.tLat),
        row("Время работы", el.tUp)),
      h("div", { class: "meter", "aria-hidden": "true" },
        h("span", { class: "meter__label" }, "Уровень сигнала"), h("div", { class: "meter__track" }, el.level)),
      h("section", { class: "timers" }, h("h3", { class: "panel__sub" }, "Таймеры"), el.timers),
      h("p", { class: "hintline" }, "Пробел — слушать · Esc — тишина · «/» — ввод · Ctrl+D — день")),
    h("section", { class: "core" }, canvas, el.caption, el.heard),
    h("aside", { class: "panel bracket panel--right" },
      h("h2", { class: "panel__title" }, "Диалог"), el.log));

  const dock = h("footer", { class: "dock" },
    el.micBtn,
    h("form", { class: "ask", autocomplete: "off", on: { submit: onAsk } },
      el.ask, h("span", { class: "ask__hint" }, "Пробел — говорить · Ctrl+D — день"),
      h("button", { class: "ask__go", type: "submit", "aria-label": "Отправить" }, "▸")),
    h("button", { class: "micbtn stopbtn", type: "button", title: "Стоп (Esc)", on: { click: stopAll } }, "Стоп"),
    h("button", { class: "dockbtn", type: "button", on: { click: () => sendText("что ты умеешь") } }, "Что умеет"),
    h("button", { class: "dockbtn", type: "button", on: { click: cycleMode } }, "Режим"));

  requestAnimationFrame(() => HUD.init(canvas));
  return h("div", { class: "hudview", style: { display: "contents" } }, view, dock);
}

export const stateChip = () => el.stateChip;

// ---------- журнал диалога ----------

function turn(who: string, text: string, kind: string, lat?: number): HTMLElement {
  const li = h("li", { class: "turn turn--" + kind },
    h("span", { class: "turn__who" }, who, lat ? h("span", { class: "turn__lat" }, lat.toFixed(2) + " с") : null),
    h("p", { class: "turn__text" }, text));
  el.log.append(li);
  while (el.log.children.length > 80) el.log.firstElementChild!.remove();
  el.log.scrollTop = el.log.scrollHeight;
  return li;
}
export const sysLog = (t: string) => turn("Система", t, "sys");

// ---------- состояние ----------

function setState(s: string): void {
  HUD.setState(s as HUD.HudState);
  el.stateChip.dataset.state = s;
  el.stateChip.textContent = CHIP[s] || s;
}

function caption(text: string, active = false): void {
  el.caption.textContent = text;
  el.caption.classList.toggle("is-active", active);
}

function applyStatus(st: any): void {
  app.status = st;
  if (confirmCard && st.pending) { setState("confirm"); caption("Нужно подтверждение", true); return; }
  setState(st.state);
  if (st.sleeping) caption("Режим ожидания — скажите «Джарвис, проснись»");
  else if (st.state === "think") caption("Думаю…", true);
  else if (st.state === "speak") caption("Ответ", true);
  else if (!micWanted) caption("Слух выключен — нажмите на реактор или пробел");
  else if (st.state === "listen" || st.open) caption("Слушаю, сэр", true);
  else caption(st.mode === "open" ? "Говорите — отвечаю без обращения" : st.mode === "ptt" ? "Говорите, пока горит кнопка" : "Скажите «Джарвис»");
  HUD.setStatusText(st.sleeping ? "СОН" : st.mode === "open" ? "ОТКРЫТ" : st.mode === "ptt" ? "КНОПКА" : st.open ? "ДИАЛОГ" : "ОЖИДАНИЕ");
  app.emit("mode", st.mode);
}

function setEngines(e: Record<string, string>, llm: boolean): void {
  const put = (dd: HTMLElement, v: string, ok: boolean) => {
    dd.textContent = v.replace(/^готово \(|\)$/g, "");
    dd.title = v;
    dd.className = ok ? "ok" : v.includes("загружа") ? "warn" : "bad";
  };
  put(el.tStt, e.stt || "—", (e.stt || "").startsWith("готово"));
  put(el.tTts, e.tts || "—", (e.tts || "").startsWith("готово"));
  put(el.tLlm, e.llm || "—", llm);
}

// ---------- микрофон ----------

export async function toggleMic(): Promise<void> {
  if (micWanted) { micWanted = false; AudioKit.setStreaming(false); link.send({ type: "mic", on: false }); updateMic(); return; }
  try {
    await AudioKit.startMic(app.settings.mic_device || undefined);
    micWanted = true;
    AudioKit.setStreaming(true, (b) => link.sendAudio(b));
    link.send({ type: "mic", on: true });
    el.tMic.textContent = "подключён"; el.tMic.className = "ok";
  } catch (err: any) {
    micWanted = false;
    const msg = String(err?.message || err);
    el.tMic.textContent = "ошибка"; el.tMic.className = "bad"; el.tMic.title = msg;
    sysLog(/запрещ/.test(msg)
      ? "Доступ к микрофону запрещён. Разрешите его в Windows: Параметры → Конфиденциальность → Микрофон. Ввод с клавиатуры работает."
      : `Микрофон не запустился: ${msg}. Ввод с клавиатуры работает.`);
    AudioKit.beep("error");
  }
  updateMic();
}

/** Как в прототипе: после входа сразу слушаем (если микрофон есть и режим не «по кнопке»). */
export function autoListen(): void {
  if (micWanted) return;
  void toggleMic();
}

function updateMic(): void {
  el.micBtn.setAttribute("aria-pressed", String(micWanted));
  el.micBtn.querySelector("#micText")!.textContent = micWanted ? "Слушаю" : "Слушать";
  if (app.status) applyStatus(app.status);
}

// ---------- команды ----------

function sendText(text: string): void {
  AudioKit.ensureCtx();
  link.send({ type: "text", text });
}

function onAsk(e: Event): void {
  e.preventDefault();
  const input = el.ask as HTMLInputElement;
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendText(text);
}

export function stopAll(): void {
  AudioKit.stopPlayback();
  link.send({ type: "stop" });
  hideConfirm();
}

function cycleMode(): void {
  const order = ["wake", "open", "ptt"];
  const next = order[(order.indexOf(app.status?.mode || "wake") + 1) % order.length];
  sendText({ wake: "только по обращению", open: "слушай постоянно", ptt: "только по кнопке" }[next as "wake"]);
}

// ---------- подтверждение ----------

function showConfirm(m: any): void {
  hideConfirm();
  AudioKit.beep("confirm");
  const danger = m.risk === "danger";
  confirmCard = h("div", { class: "confirm bracket" + (danger ? " confirm--danger" : ""), role: "alertdialog" },
    h("p", { class: "confirm__eyebrow" }, danger ? "Необратимое действие" : "Нужно подтверждение"),
    h("p", { class: "confirm__title" }, m.title),
    m.details ? h("p", { class: "muted" }, m.details) : null,
    h("div", { class: "row" },
      h("button", { class: "btn " + (danger ? "btn--danger" : "btn--gold"), type: "button",
        on: { click: () => { link.send({ type: "confirm", id: m.id, ok: true }); hideConfirm(); } } }, "Подтвердить"),
      h("button", { class: "btn btn--ghost", type: "button",
        on: { click: () => { link.send({ type: "confirm", id: m.id, ok: false }); hideConfirm(); } } }, "Отмена"),
      h("span", { class: "muted" }, "или скажите «да» / «нет»")));
  document.body.append(confirmCard);
  setState("confirm");
}

function hideConfirm(): void { confirmCard?.remove(); confirmCard = null; }

// ---------- таймеры ----------

let timers: { id: number; label: string; left: number; at: number }[] = [];
function renderTimers(): void {
  el.timers.replaceChildren();
  if (!timers.length) { el.timers.append(h("li", { class: "timers__empty" }, "нет активных")); return; }
  for (const t of timers) {
    const left = Math.max(0, Math.round((t.at - Date.now()) / 1000));
    el.timers.append(h("li", null, h("span", null, t.label.slice(0, 22)),
      h("b", null, String(Math.floor(left / 60)).padStart(2, "0") + ":" + String(left % 60).padStart(2, "0"))));
  }
}

// ---------- подписка на события ядра ----------

export function wire(): void {
  link.on("hello", (m) => {
    startedAt = Date.now();
    setEngines(m.engines, m.llm);
    applyStatus(m.status);
    timers = (m.timers || []).map((t: any) => ({ ...t, at: Date.now() + t.left * 1000 }));
    renderTimers();
  });
  link.on("status", applyStatus);
  link.on("engines", (m) => setEngines(m.engines, m.llm));
  link.on("line", (m) => {
    if (m.kind === "user") { heard++; el.tHeard.textContent = String(heard); }
    if (m.kind === "jarvis" && m.intent && !["unknown", "error"].includes(m.intent)) { done++; el.tDone.textContent = String(done); }
    if (m.latency) el.tLat.textContent = m.latency.toFixed(2) + " с";
    turn(m.who, m.text, m.kind, m.kind === "jarvis" ? m.latency : undefined);
  });
  link.on("heard", (m) => {
    el.heard.classList.toggle("is-final", !!m.final);
    el.heard.textContent = m.text;
  });
  link.on("audio", (m) => { pendingVolume = m.volume ?? 1; pendingText = m.text || ""; });
  link.onAudio((buf) => AudioKit.enqueueWav(buf, pendingVolume, pendingText));
  link.on("say", (m) => AudioKit.enqueueText(m.text, m.volume ?? 1));
  link.on("audio_stop", () => AudioKit.stopPlayback());
  link.on("beep", (m) => AudioKit.beep(m.name, m.name === "ack" ? 0.5 : 1));
  link.on("confirm", showConfirm);
  link.on("confirm_done", hideConfirm);
  link.on("timers", (m) => { timers = m.items.map((t: any) => ({ ...t, at: Date.now() + t.left * 1000 })); renderTimers(); });
  link.on("notify", (m) => {
    if (shell) shell.notify(m.title, m.body);
    else if ("Notification" in window && Notification.permission === "granted") new Notification(m.title, { body: m.body });
    toast(m.body);
  });
  link.on("ui", (m) => {
    if (m.action === "fullscreen") document.documentElement.requestFullscreen?.();
    if (m.action === "clear_log") el.log.replaceChildren();
    if (m.action === "day_sheet") toggleDaySheet(true);
    if (m.action === "listen" && !micWanted) void toggleMic();
    if (m.action === "shutdown") setTimeout(() => shell ? shell.quit() : window.close(), m.delay || 2000);
  });
  link.on("link", (m) => {
    if (!m.up) { setState("error"); caption("Нет связи с ядром — переподключаюсь…"); }
    else if (micWanted) link.send({ type: "mic", on: true });
  });

  AudioKit.onPlayback(
    () => { HUD.speechPulse(0.6); },
    () => link.send({ type: "playback", playing: false }));

  setInterval(() => {
    const up = Math.round((Date.now() - startedAt) / 1000);
    el.tUp.textContent = clockFromSec(up);
    if (timers.length) renderTimers();
    app.emit("clock", hhmmss());
  }, 1000);
  setInterval(() => {
    el.level.style.width = Math.round(Math.min(1, AudioKit.getLevel() * 1.4) * 100) + "%";
  }, 100);

  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement as HTMLElement)?.tagName || "");
    if (e.key === "Escape") { stopAll(); (el.ask as HTMLInputElement).blur(); return; }
    if (e.ctrlKey && (e.key === "d" || e.key === "в")) { e.preventDefault(); toggleDaySheet(); return; }
    if (typing || app.route !== "hud") return;
    if (e.code === "Space") { e.preventDefault(); void toggleMic(); }
    if (e.key === "/" || e.key === ".") { e.preventDefault(); (el.ask as HTMLInputElement).focus(); }
  });
  shell?.onHotkey(() => { if (!micWanted) void toggleMic(); });
}

let pendingVolume = 1;
let pendingText = "";

export function bootGreeting(): void {
  HUD.revealIn();
  AudioKit.beep("boot");
  sysLog("Система запущена. Распознавание речи, нейросеть и голос работают на этом компьютере.");
}
