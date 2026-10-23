/* ============================================================
   Настройки: модели, микрофон, голос, слух, горячие клавиши,
   внешний вид, приватность (датасет для дообучения — по согласию,
   по умолчанию выключен), белый список инструментов,
   системный промпт характера Джарвиса.
   ============================================================ */

import { api, shell } from "../api";
import * as AudioKit from "../audio";
import { applyAccent } from "../state";
import { field, h, RISK_TITLE, toast } from "../ui";
import { playSample } from "./wizard";

export async function settingsView(onWizard: () => void): Promise<HTMLElement> {
  const [{ settings: s, tools }, check] = await Promise.all([api("/api/settings"), api("/api/setup/check")]);
  const put = (body: object, quiet = false) => api("/api/settings", { method: "PUT", body })
    .then(() => { if (!quiet) toast("Сохранено"); }).catch((e) => toast(e.message, true));

  const select = (key: string, opts: [string, string][]) => {
    const el = h("select", { class: "input" }, opts.map(([v, t]) => h("option", { value: v, selected: String(s[key]) === v }, t))) as HTMLSelectElement;
    el.onchange = () => void put({ [key]: el.value });
    return el;
  };
  const num = (key: string, min: number, max: number, step: number) => {
    const el = h("input", { class: "input", type: "number", min, max, step, value: String(s[key]) }) as HTMLInputElement;
    el.onchange = () => void put({ [key]: Number(el.value) });
    return el;
  };
  const check_ = (key: string, label: string, onChange?: (v: boolean) => void) => {
    const el = h("input", { type: "checkbox", checked: !!s[key] }) as HTMLInputElement;
    el.onchange = () => { void put({ [key]: el.checked }); onChange?.(el.checked); };
    return h("label", { class: "check" }, el, label);
  };

  const llmOpts: [string, string][] = Array.from(new Set([s.llm_model, ...check.llm_models.filter((m: string) => !/embed/.test(m))]))
    .map((m) => [m as string, m as string]);
  const mics = await AudioKit.listMics().catch(() => []);
  const micSel = h("select", { class: "input" }, h("option", { value: "" }, "по умолчанию"),
    mics.map((m) => h("option", { value: m.deviceId, selected: m.deviceId === s.mic_device }, m.label || "Микрофон"))) as HTMLSelectElement;
  micSel.onchange = () => void put({ mic_device: micSel.value });

  const hotkey = h("input", { class: "input", value: s.hotkey_global }) as HTMLInputElement;
  hotkey.onchange = async () => {
    const ok = shell ? await shell.setHotkey(hotkey.value) : true;
    if (!ok) { toast("Это сочетание занято другой программой", true); return; }
    void put({ hotkey_global: hotkey.value });
  };
  const accent = h("input", { type: "color", value: s.accent || "#5ad9ff" }) as HTMLInputElement;
  accent.oninput = () => applyAccent(accent.value);
  accent.onchange = () => void put({ accent: accent.value });

  const prompt = h("textarea", { class: "input", spellcheck: false }) as HTMLTextAreaElement;
  prompt.value = s.system_prompt || (await api("/api/prompt/default")).prompt;

  const disabled = new Set<string>(s.disabled_tools || []);
  const toolRows = tools.map((t: any) => {
    const cb = h("input", { type: "checkbox", checked: !disabled.has(t.name) }) as HTMLInputElement;
    cb.onchange = () => { cb.checked ? disabled.delete(t.name) : disabled.add(t.name); void put({ disabled_tools: [...disabled] }, true); };
    return h("tr", null, h("td", null, cb), h("td", null, t.title, h("div", { class: "meta muted" }, t.name)),
      h("td", null, h("span", { class: "tag tag--" + t.risk }, RISK_TITLE[t.risk])), h("td", null, t.network ? "сеть" : ""));
  });

  return h("div", { class: "page" },
    h("div", { class: "page__head" }, h("h1", { class: "page__title" }, "Настройки"),
      h("button", { class: "btn btn--ghost", type: "button", on: { click: onWizard } }, "Мастер первого запуска")),
    h("div", { class: "cols" },
      h("div", { class: "card bracket" }, h("h3", null, "Модели"),
        field("Профиль железа", select("hw_profile", [["lite", "Лёгкий"], ["standard", "Стандартный"], ["max", "Максимальный"]])),
        field("Нейросеть (Ollama)", select("llm_model", llmOpts), "Скачать другую: мастер первого запуска или «ollama pull имя» в терминале."),
        field("Температура", num("llm_temperature", 0, 1.5, 0.1), "Ниже — точнее, выше — живее."),
        field("Реплик в контексте", num("llm_ctx_turns", 2, 30, 1)),
        field("Модель эмбеддингов (поиск по документам)", select("embed_model", [["nomic-embed-text", "nomic-embed-text"], ["bge-m3", "bge-m3 (лучше для русского, 1,2 ГБ)"]])),
        field("Распознавание Whisper", select("whisper_model", [["base", "base — быстро"], ["small", "small — баланс"], ["medium", "medium — точно, медленнее"]])),
        field("Устройство распознавания", select("whisper_device", [["auto", "авто (видеокарта, иначе процессор)"], ["cuda", "видеокарта"], ["cpu", "процессор"]])),
        h("p", { class: "muted mono" }, Object.entries(check.engines).map(([k, v]) => `${k}: ${v}`).join("\n"))),
      h("div", { class: "card" }, h("h3", null, "Голос и слух"),
        field("Микрофон", micSel),
        field("Режим", select("listen_mode", [["wake", "по слову «Джарвис»"], ["ptt", "по кнопке / горячей клавише"], ["open", "постоянно"]])),
        field("Голос", select("tts_voice", Object.entries(check.voices).filter(([, ok]) => ok).map(([v]) => [v, v.split("-")[1]] as [string, string]))),
        field("Движок синтеза", select("tts_engine", [["piper", "Piper (офлайн, по умолчанию)"], ["silero", "Silero (нужен torch)"], ["client", "голос Windows"]])),
        field("Скорость речи", num("tts_rate", 0.6, 1.6, 0.05)),
        h("button", { class: "btn btn--ghost", type: "button", on: { click: () => void playSample() } }, "Послушать"),
        h("p", { class: "muted" }, "Слово обращения — «Джарвис». Пока Джарвис говорит, слух приглушён: перебить можно словами «стоп» или «Джарвис …».")),
      h("div", { class: "card" }, h("h3", null, "Приложение"),
        field("Горячая клавиша вызова (глобальная)", hotkey, "Формат Electron: Control+Alt+J, CommandOrControl+Shift+Space"),
        check_("autostart", "Запускать вместе с Windows", (v) => void shell?.setAutostart(v)),
        field("Акцентный цвет", accent),
        check_("order_automation", "Заказы: собирать корзину в браузере автоматически (этап 2, видимое окно)"),
        h("p", { class: "muted" }, "Клавиши в окне: пробел — слушать, Esc — тишина и отмена, «/» — ввод, Ctrl+D — шторка «День».")),
      h("div", { class: "card" }, h("h3", null, "Приватность"),
        h("p", { class: "muted" }, "Речь, нейросеть, память и почта обрабатываются на этом компьютере. В сеть — только по вашей явной просьбе: погода, справка, «найди в сети», почтовый сервер, сайт магазина. Телеметрии нет."),
        check_("collect_dataset", "Собирать мои диалоги для дообучения модели (хранятся локально)"),
        h("div", { class: "row" },
          h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => {
            const text = await api<string>("/api/dataset");
            const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "application/jsonl" })), download: "jarvis-dataset.jsonl" }); a.click();
          } } }, "Выгрузить JSONL"),
          h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => { await api("/api/dataset", { method: "DELETE" }); toast("Датасет очищен"); } } }, "Очистить датасет"))),
      h("div", { class: "card", style: { gridColumn: "1 / -1" } }, h("h3", null, "Инструменты (белый список)"),
        h("p", { class: "muted" }, "Снимите галочку — Джарвис не сможет выполнить это действие ни по правилу, ни по решению нейросети. «Снаружи» и «необратимо» всегда требуют подтверждения; отключить подтверждение нельзя."),
        h("table", { class: "tbl" }, h("tbody", null, toolRows))),
      h("div", { class: "card", style: { gridColumn: "1 / -1" } }, h("h3", null, "Характер (системный промпт)"),
        h("p", { class: "muted" }, "Подстановки: {address} — обращение, {tools} — список инструментов, {now} — дата и время, {city} — город. Фигурные скобки в тексте удваивайте: {{ }}."),
        prompt,
        h("div", { class: "row" },
          h("button", { class: "btn", type: "button", on: { click: () => void put({ system_prompt: prompt.value }) } }, "Сохранить"),
          h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => {
            prompt.value = (await api("/api/prompt/default")).prompt; void put({ system_prompt: "" });
          } } }, "Вернуть по умолчанию")))));
}
