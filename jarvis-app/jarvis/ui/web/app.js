// Джарвис — интерфейс «Орбита». Всё общение с ядром — через локальный API.
(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="jarvis-token"]').content;
  const $ = (id) => document.getElementById(id);
  const app = $("app");
  const ACCENTS = ["#5EEAD4", "#7AA2F7", "#C4A7E7", "#F6C177", "#F7768E", "#9ECE6A"];
  const STATE_LABELS = { idle: "", listening: "Слушаю…", thinking: "Думаю…", executing: "Выполняю…", confirm: "", error: "" };

  let state = null;          // последнее состояние ядра
  let pendingId = null;      // id подтверждения
  let lastCommand = null;    // для кнопки «Повторить»

  // ---- API ---------------------------------------------------------------
  async function api(path, body, opts = {}) {
    const res = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-Jarvis-Token": TOKEN, ...(opts.raw ? { "Content-Type": opts.type } : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : (opts.raw ? body : JSON.stringify(body)),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok && !data.say) throw new Error(data.error || `Ошибка ${res.status}`);
    return data;
  }

  // ---- состояния главного окна ------------------------------------------
  function setState(s) {
    app.dataset.state = s;
    $("stateLabel").textContent = STATE_LABELS[s] ?? "";
  }

  function showAnswer(r) {
    const said = $("said"), steps = $("steps"), actions = $("actions");
    steps.innerHTML = ""; actions.innerHTML = "";
    said.classList.remove("heard");
    said.textContent = r.say || "";
    if (r.steps && r.steps.length > 1) {
      for (const s of r.steps) {
        const li = document.createElement("li");
        li.textContent = s.text;
        if (!s.ok) li.className = "fail";
        steps.append(li);
      }
    }
    if (r.undo) actions.append(button("Отменить", "btn ghost", undo));
    if (r.status === "error" && lastCommand) actions.append(button("Повторить", "btn", () => send(lastCommand)));
  }

  function button(text, cls, onClick) {
    const b = document.createElement("button");
    b.className = cls; b.textContent = text; b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function handleResult(r) {
    if (r.day) renderDay(r.day);
    if (typeof r.stopped === "boolean") renderStopped(r.stopped);
    $("confirm").hidden = true; pendingId = null;

    if (r.status === "confirm") {
      setState("confirm");
      pendingId = r.confirm.id;
      $("said").textContent = r.heard || "";
      $("steps").innerHTML = ""; $("actions").innerHTML = "";
      $("confirmText").textContent = r.confirm.text;
      $("confirmReason").textContent = r.confirm.reason;
      $("confirm").hidden = false;
      $("confirmYes").focus();
      return;
    }
    setState(r.status === "done" ? "idle" : "error");
    showAnswer(r);
    if (r.ui?.open_day) toggleSheet(true);
  }

  async function send(text, viaDaySheet = false) {
    text = text.trim();
    if (!text) return;
    lastCommand = text;
    setState("thinking");
    $("said").textContent = text;
    $("steps").innerHTML = ""; $("actions").innerHTML = "";
    try {
      let r = await api("/api/command", { text });
      // В шторке «День» нераспознанный текст — это новая задача.
      if (viaDaySheet && r.status === "unknown") r = await api("/api/command", { text: "добавь задачу " + text });
      handleResult(r);
    } catch (e) {
      setState("error");
      showAnswer({ status: "error", say: "Ядро не отвечает. " + e.message });
    }
  }

  async function confirm(accept) {
    if (!pendingId) return;
    setState(accept ? "executing" : "idle");
    handleResult(await api("/api/confirm", { id: pendingId, accept }));
  }

  async function undo() { handleResult(await api("/api/undo", {})); }

  // ---- кольцо дня --------------------------------------------------------
  const SVG = "http://www.w3.org/2000/svg";
  function el(name, attrs) {
    const e = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }

  function renderRing(day) {
    const ring = $("ring");
    ring.innerHTML = "";
    const C = 150, R = 118, DASHES = 48;              // 48 штрихов = по 30 минут
    const frac = day.now_minutes / 1440;
    const step = (2 * Math.PI) / DASHES;
    for (let i = 0; i < DASHES; i++) {
      const a0 = -Math.PI / 2 + i * step + step * 0.18;
      const a1 = -Math.PI / 2 + (i + 1) * step - step * 0.18;
      const d = `M ${C + R * Math.cos(a0)} ${C + R * Math.sin(a0)} A ${R} ${R} 0 0 1 ${C + R * Math.cos(a1)} ${C + R * Math.sin(a1)}`;
      ring.append(el("path", { d, fill: "none", "stroke-width": 4, "stroke-linecap": "round",
        class: (i + 1) / DASHES <= frac ? "dash-past" : "dash-future" }));
    }
    // точка «сейчас»
    const an = -Math.PI / 2 + frac * 2 * Math.PI;
    ring.append(el("circle", { cx: C + R * Math.cos(an), cy: C + R * Math.sin(an), r: 5, class: "now" }));
    // задачи — точки снаружи кольца
    for (const t of day.tasks) {
      if (!t.time) continue;
      const [h, m] = t.time.split(":").map(Number);
      const a = -Math.PI / 2 + ((h * 60 + m) / 1440) * 2 * Math.PI;
      const c = el("circle", { cx: C + (R + 20) * Math.cos(a), cy: C + (R + 20) * Math.sin(a), r: 5,
        class: t.status === "done" ? "task-done" : "task-open" });
      const title = el("title", {}); title.textContent = `${t.time} ${t.title}`;
      c.append(title);
      ring.append(c);
    }
  }

  // ---- шторка «День» -----------------------------------------------------
  function renderDay(day) {
    state && (state.day = day);
    renderRing(day);
    const { done, total } = day.counts;
    $("tabLabel").textContent = total ? `День · ${done} из ${total} задач` : "День · задач нет";
    $("dateLabel").textContent = day.date_label;
    $("doneCount").textContent = total ? `Сделано ${done} из ${total}` : "";

    const plan = $("plan");
    plan.innerHTML = "";
    if (!day.tasks.length) plan.innerHTML = '<li class="empty">Пока пусто — скажите «добавь задачу…»</li>';
    for (const t of day.tasks) {
      const li = document.createElement("li");
      if (t.status === "done") li.className = "done";
      const time = document.createElement("span"); time.className = "time"; time.textContent = t.time || "—";
      const check = document.createElement("button");
      check.className = "check" + (t.status === "done" ? " done" : "");
      check.setAttribute("aria-label", (t.status === "done" ? "Вернуть в план: " : "Отметить выполненной: ") + t.title);
      check.addEventListener("click", async () => handleResult(await api("/api/task/toggle", { id: t.id })));
      const title = document.createElement("span"); title.className = "title"; title.textContent = t.title;
      if (t.created_by === "assistant") {
        const by = document.createElement("span"); by.className = "by"; by.textContent = "· Джарвис"; title.append(by);
      }
      li.append(time, check, title);
      plan.append(li);
    }

    const log = $("log");
    log.innerHTML = "";
    if (!day.done.length) log.innerHTML = '<li class="empty">Сегодня ещё ничего не делал</li>';
    for (const e of day.done) {
      const li = document.createElement("li");
      if (e.status === "undone") li.className = "undone";
      const time = document.createElement("span"); time.className = "time"; time.textContent = e.time;
      const text = document.createElement("span"); text.className = "text"; text.textContent = e.text;
      li.append(time, text);
      log.append(li);
    }
  }

  function toggleSheet(force) {
    const open = force ?? !$("sheet").classList.contains("open");
    $("sheet").classList.toggle("open", open);
    $("sheet").setAttribute("aria-hidden", String(!open));
    app.classList.toggle("sheet-open", open);
    $("dayTab").setAttribute("aria-expanded", String(open));
    $("input").placeholder = open ? "Добавить задачу голосом или текстом…" : "Или напишите команду…";
    $("hint").hidden = open;
  }

  // ---- аварийная остановка / настройки ----------------------------------
  function statusText() {
    if (state?.voice?.backend === "api") return "Голос через облако · остальное локально";
    return "Локально · без интернета";
  }

  function renderStopped(stopped) {
    $("stoppedBanner").hidden = !stopped;
    $("status").classList.toggle("off", stopped);
    $("statusText").textContent = stopped ? "Остановлен" : statusText();
  }

  function applyAccent(hex) {
    document.documentElement.style.setProperty("--accent", hex);
    for (const s of document.querySelectorAll(".swatch")) s.setAttribute("aria-pressed", String(s.dataset.c === hex));
  }

  function renderSettings(s) {
    const sw = $("swatches");
    if (!sw.children.length) {
      for (const c of ACCENTS) {
        const b = document.createElement("button");
        b.className = "swatch"; b.dataset.c = c; b.style.background = c; b.setAttribute("aria-label", "Цвет " + c);
        b.addEventListener("click", async () => { applyAccent(c); await api("/api/settings", { accent: c }); });
        sw.append(b);
      }
    }
    applyAccent(s.accent);
    $("ttsToggle").checked = s.voice.tts_on;
    $("ttsToggle").disabled = !s.voice.tts;
    const v = s.voice;
    $("sttMode").value = v.mode;
    $("sttApi").hidden = v.mode === "local";
    const prov = $("sttProvider");
    prov.innerHTML = "";
    for (const [k, title] of Object.entries(v.providers)) prov.append(new Option(title, k, false, k === v.provider));
    $("sttKey").value = "";
    $("sttKey").placeholder = v.api_key_set ? "Ключ сохранён — введите новый, чтобы заменить" : "Ключ API";
    $("keyInfo").textContent = v.api_key_set
      ? "Ключ хранится в защищённом хранилище системы. Аудио отправляется в облако только при нажатии микрофона."
      : "Ключ хранится в защищённом хранилище системы, в коде и в базе его нет.";
    const sel = $("profileSel");
    sel.innerHTML = "";
    for (const [k, title] of Object.entries(s.profiles)) sel.append(new Option(title, k, false, k === s.profile));
    const llm = s.llm.enabled ? `Локальная модель: ${s.llm.model}` : "Локальная модель не найдена — работает только роутер правил";
    const voice = s.voice.backend === "api" ? "голос через API" : s.voice.backend === "local" ? "голос локально" : "голос не настроен";
    $("llmInfo").textContent = `${llm}; ${voice}${s.dry_run ? "; тестовый режим" : ""}.`;
  }

  // ---- голос: push-to-talk ----------------------------------------------
  let recorder = null, chunks = [];

  async function startListening() {
    if (recorder || app.dataset.state === "thinking") return;
    if (state && !state.voice.stt) {
      setState("error");
      showAnswer({ status: "error", say: "Голос не настроен: добавьте ключ API в настройках (⚙). Пока можно писать текстом." });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        recorder = null;
        if (blob.size < 2000) { setState("idle"); return; }
        setState("thinking");
        $("said").textContent = "Распознаю…";
        try {
          const r = await api("/api/voice", blob, { raw: true, type: blob.type });
          if (r.heard) lastCommand = r.heard;
          handleResult(r);
          if (r.heard && r.status !== "confirm") {
            const h = document.createElement("div"); h.className = "said heard"; h.textContent = `«${r.heard}»`;
            $("said").before(h); setTimeout(() => h.remove(), 6000);
          }
        } catch (e) { setState("error"); showAnswer({ status: "error", say: e.message }); }
      };
      recorder.start();
      setState("listening");
      $("said").textContent = "Говорите…";
    } catch {
      setState("error");
      showAnswer({ status: "error", say: "Нет доступа к микрофону" });
    }
  }

  function stopListening() { if (recorder && recorder.state === "recording") recorder.stop(); }

  // ---- события -----------------------------------------------------------
  $("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("input").value;
    $("input").value = "";
    send(text, $("sheet").classList.contains("open"));
  });
  $("dayTab").addEventListener("click", () => toggleSheet());
  $("collapse").addEventListener("click", () => toggleSheet(false));
  $("confirmYes").addEventListener("click", () => confirm(true));
  $("confirmNo").addEventListener("click", () => confirm(false));
  $("resumeBtn").addEventListener("click", async () => handleResult(await api("/api/resume", {})));
  $("stopBtn").addEventListener("click", async () => { handleResult(await api("/api/stop", {})); $("settings").hidden = true; });
  $("wipeBtn").addEventListener("click", async () => {
    if (!window.confirm("Удалить все задачи, журнал и настройки?")) return;
    state = await api("/api/wipe", {}); renderAll();
  });
  const saveSettings = async (patch) => {
    try { state = await api("/api/settings", patch); renderSettings(state); renderStopped(state.stopped); }
    catch (e) { $("keyInfo").textContent = e.message; }
  };
  $("sttMode").addEventListener("change", (e) => saveSettings({ stt_backend: e.target.value }));
  $("sttProvider").addEventListener("change", (e) => saveSettings({ stt_provider: e.target.value }));
  $("keyForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const key = $("sttKey").value.trim();
    if (key) saveSettings({ stt_api_key: key, stt_backend: "auto" });
  });
  $("ttsToggle").addEventListener("change", (e) => api("/api/settings", { tts_on: e.target.checked }));
  $("profileSel").addEventListener("change", async (e) => { state = await api("/api/settings", { profile: e.target.value }); renderSettings(state); });
  $("settingsBtn").addEventListener("click", () => {
    const s = $("settings"); s.hidden = !s.hidden;
    $("settingsBtn").setAttribute("aria-expanded", String(!s.hidden));
  });

  for (const b of [$("mic"), $("miniMic")]) {
    b.addEventListener("pointerdown", startListening);
    b.addEventListener("pointerup", stopListening);
    b.addEventListener("pointerleave", stopListening);
  }

  const typing = () => document.activeElement && ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.code === "KeyD") { e.preventDefault(); toggleSheet(); return; }
    if (e.key === "Escape") {
      if (!$("confirm").hidden) confirm(false);
      else if (!$("settings").hidden) $("settings").hidden = true;
      else toggleSheet(false);
      return;
    }
    if (e.code === "Space" && !typing() && !e.repeat && $("confirm").hidden) {
      if (document.activeElement?.tagName === "BUTTON") return;  // Пробел на кнопке — это нажатие
      e.preventDefault(); startListening();
    }
  });
  document.addEventListener("keyup", (e) => { if (e.code === "Space") stopListening(); });

  // ---- старт -------------------------------------------------------------
  function renderAll() {
    renderDay(state.day);
    renderStopped(state.stopped);
    renderSettings(state);
  }

  async function refresh() {
    try { state = await api("/api/state"); renderAll(); }
    catch { renderStopped(false); $("statusText").textContent = "Ядро не отвечает"; $("status").classList.add("off"); }
  }

  refresh();
  setInterval(async () => { try { renderDay(await api("/api/day")); } catch {} }, 60_000);
})();
