/* ============================================================
   Мастер первого запуска: микрофон → проверка Whisper и Ollama →
   скачивание моделей с прогрессом (только по кнопке — это
   единственный момент, когда ядро ходит в сеть без вопроса в чате)
   → выбор голоса → как к вам обращаться.
   ============================================================ */

import { api, sse } from "../api";
import * as AudioKit from "../audio";
import { field, h, toast } from "../ui";

const VOICES: Record<string, string> = {
  "ru_RU-denis-medium": "Денис — спокойный мужской",
  "ru_RU-dmitri-medium": "Дмитрий — низкий мужской",
  "ru_RU-ruslan-medium": "Руслан — бодрый мужской",
  "ru_RU-irina-medium": "Ирина — женский",
};

/** Проба голоса: ядро синтезирует фразу выбранным голосом (голос грузится пару секунд после смены). */
export async function playSample(): Promise<void> {
  for (let i = 0; i < 6; i++) {
    try {
      const wav = await api<ArrayBuffer>("/api/tts/sample", { raw: true });
      AudioKit.enqueueWav(wav);
      return;
    } catch (e: any) {
      if (i === 5) toast("Голос ядра не готов: " + e.message + ". Будет использован голос Windows.", true);
      await new Promise((r) => setTimeout(r, 800));
    }
  }
}

export function wizard(onDone: () => void): HTMLElement {
  const root = h("div", { class: "gate" });
  const inner = h("div", { class: "gate__inner" });
  root.append(inner);
  let step = 0;
  let check: any = null;
  const steps = [micStep, modelsStep, voiceStep, aboutStep];

  const frame = (title: string, desc: string, ...body: (HTMLElement | null)[]) => inner.replaceChildren(
    h("div", { class: "steps" }, steps.map((_, i) => h("i", { class: i <= step ? "on" : "" }))),
    h("h2", { class: "page__title" }, title),
    h("p", { class: "gate__desc" }, desc),
    ...body.filter(Boolean) as HTMLElement[]);

  const nav = (canNext = true) => h("div", { class: "row" },
    step > 0 ? h("button", { class: "btn btn--ghost", type: "button", on: { click: () => go(step - 1) } }, "Назад") : null,
    h("button", { class: "btn", type: "button", disabled: !canNext, on: { click: () => go(step + 1) } },
      step === steps.length - 1 ? "Готово" : "Дальше"));

  function go(i: number): void {
    if (i >= steps.length) { void finish(); return; }
    step = i;
    void steps[i]();
  }

  // ---------- 1. микрофон ----------
  async function micStep(): Promise<void> {
    const bar = h("i");
    const sel = h("select", { class: "input" }) as HTMLSelectElement;
    const status = h("p", { class: "muted" }, "Скажите что-нибудь — полоса должна двигаться.");
    frame("Микрофон", "Джарвис слушает через микрофон. Звук обрабатывается здесь же, в сеть не уходит.",
      h("div", { class: "card bracket" }, field("Устройство", sel), h("div", { class: "progress" }, bar), status), nav());
    try {
      await AudioKit.startMic();
      const mics = await AudioKit.listMics();
      sel.replaceChildren(...mics.map((m) => h("option", { value: m.deviceId }, m.label || "Микрофон")));
      sel.onchange = async () => { AudioKit.stopMic(); await AudioKit.startMic(sel.value); void api("/api/settings", { method: "PUT", body: { mic_device: sel.value } }).catch(() => {}); };
      const t = setInterval(() => {
        if (!document.body.contains(bar)) { clearInterval(t); return; }
        AudioKit.tick();
        bar.style.width = Math.round(Math.min(1, AudioKit.getLevel() * 1.4) * 100) + "%";
      }, 60);
    } catch {
      status.textContent = "Нет доступа к микрофону. Разрешите его в Windows: Параметры → Конфиденциальность → Микрофон. Можно продолжить и пользоваться клавиатурой.";
      status.className = "error";
    }
  }

  // ---------- 2. модели ----------
  async function modelsStep(): Promise<void> {
    frame("Проверка систем", "Смотрю, что уже есть на компьютере.", h("p", { class: "muted" }, "Проверяю…"));
    try { check = await api("/api/setup/check"); } catch (e: any) { toast(e.message, true); return; }
    const hw = check.hw;
    const llm = check.settings.llm_model || hw.llm;
    const whisper = check.settings.whisper_model || hw.whisper;
    const has = (name: string) => check.llm_models.some((m: string) => m === name || m === name + ":latest");
    const embed = check.settings.embed_model;

    const row = (ok: boolean | "warn", label: string, extra: HTMLElement | string | null) =>
      h("div", { class: "checkrow" }, h("span", { class: "dot " + (ok === "warn" ? "warn" : ok ? "ok" : "bad") }), h("span", null, label), extra);
    const progress = h("div", { class: "progress" }, h("i"));
    const plabel = h("p", { class: "muted mono" });

    const pull = async (path: string, name: string, title: string) => {
      plabel.textContent = title + "…";
      await sse(path, { name }, (d) => {
        if (d.error) { toast(d.error, true); return; }
        if (d.total) (progress.firstChild as HTMLElement).style.width = Math.round((100 * d.completed) / d.total) + "%";
        if (d.status) plabel.textContent = `${title}: ${d.status}` + (d.total ? ` — ${Math.round(d.completed / 1048576)} / ${Math.round(d.total / 1048576)} МБ` : "");
      });
      plabel.textContent = title + " — готово";
      await modelsStep();
    };
    const dl = (path: string, name: string, title: string) =>
      h("button", { class: "btn btn--sm", type: "button", on: { click: (e: Event) => { (e.target as HTMLButtonElement).disabled = true; void pull(path, name, title); } } }, "Скачать");

    const profileSel = h("select", { class: "input" }, ["lite", "standard", "max"].map((p) =>
      h("option", { value: p, selected: p === (check.settings.hw_profile || hw.profile) }, { lite: "Лёгкий — Whisper base, Qwen 1.5B", standard: "Стандартный — Whisper small, Qwen 7B", max: "Максимальный — Whisper medium, Qwen 7B" }[p]!))) as HTMLSelectElement;
    profileSel.onchange = async () => {
      const map: Record<string, [string, string]> = { lite: ["base", "qwen2.5:1.5b"], standard: ["small", "qwen2.5:7b"], max: ["medium", "qwen2.5:7b"] };
      const [w, l] = map[profileSel.value];
      await api("/api/settings", { method: "PUT", body: { hw_profile: profileSel.value, whisper_model: w, llm_model: l } });
      await modelsStep();
    };

    frame("Проверка систем", `Видеокарта: ${hw.gpu || "не найдена"}${hw.vram_mb ? ` (${Math.round(hw.vram_mb / 1024)} ГБ)` : ""}, ОЗУ ${hw.ram_gb} ГБ. Рекомендую профиль «${hw.title}».`,
      h("div", { class: "card bracket" },
        field("Профиль железа", profileSel),
        row(check.ollama, "Ollama (локальный сервер нейросети)", check.ollama ? "работает" : h("span", { class: "muted" }, "не запущена — установите с ollama.com")),
        row(has(llm), `Нейросеть ${llm}`, has(llm) ? "есть" : check.ollama ? dl("/api/setup/pull", llm, llm) : null),
        row(check.whisper_models.includes(whisper), `Распознавание речи Whisper ${whisper}`,
          check.whisper_models.includes(whisper) ? "есть" : dl("/api/setup/whisper", whisper, "Whisper " + whisper)),
        row(has(embed) || "warn", `Поиск по документам (${embed}) — необязательно`, has(embed) ? "есть" : check.ollama ? dl("/api/setup/pull", embed, embed) : null),
        h("p", { class: "muted" }, `Движки: ${Object.entries(check.engines).map(([k, v]) => k + " — " + v).join("; ")}`),
        progress, plabel),
      nav(true));
  }

  // ---------- 3. голос ----------
  async function voiceStep(): Promise<void> {
    if (!check) check = await api("/api/setup/check");
    const cur = check.settings.tts_voice;
    const rate = h("input", { type: "range", min: "0.7", max: "1.4", step: "0.05", value: String(check.settings.tts_rate || 1) }) as HTMLInputElement;
    const progress = h("div", { class: "progress" }, h("i"));
    const list = h("div", { class: "list" }, Object.entries(VOICES).map(([id, title]) => {
      const have = check.voices[id];
      return h("div", { class: "checkrow" },
        h("input", { type: "radio", name: "voice", value: id, checked: id === cur, disabled: !have,
          on: { change: () => void api("/api/settings", { method: "PUT", body: { tts_voice: id } }) } }),
        h("span", null, title),
        have ? h("span", { class: "muted" }, "есть") : h("button", { class: "btn btn--sm", type: "button", on: { click: async () => {
          await sse("/api/setup/voice", { name: id }, (d) => { if (d.total) (progress.firstChild as HTMLElement).style.width = Math.round(100 * d.completed / d.total) + "%"; });
          check = await api("/api/setup/check");
          void voiceStep();
        } } }, "Скачать"));
    }));
    rate.onchange = () => void api("/api/settings", { method: "PUT", body: { tts_rate: Number(rate.value) } });
    frame("Голос", "Синтез речи Piper работает офлайн. Если голос не скачан, Джарвис говорит голосом Windows.",
      h("div", { class: "card bracket" }, list, progress, field("Скорость речи", rate),
        h("button", { class: "btn btn--ghost", type: "button", on: { click: () => void playSample() } }, "Послушать")),
      nav());
  }

  // ---------- 4. о вас ----------
  async function aboutStep(): Promise<void> {
    const s = (await api("/api/settings")).settings;
    const address = h("input", { class: "input", value: s.address_as }) as HTMLInputElement;
    const city = h("input", { class: "input", value: s.city }) as HTMLInputElement;
    const mode = h("select", { class: "input" },
      h("option", { value: "wake", selected: s.listen_mode === "wake" }, "По слову «Джарвис»"),
      h("option", { value: "ptt", selected: s.listen_mode === "ptt" }, "Только по кнопке / горячей клавише"),
      h("option", { value: "open", selected: s.listen_mode === "open" }, "Постоянно (отвечать на всё)")) as HTMLSelectElement;
    const save = () => api("/api/settings", { method: "PUT", body: { address_as: address.value.trim() || "сэр", city: city.value.trim(), listen_mode: mode.value } });
    address.onchange = city.onchange = mode.onchange = () => void save();
    frame("О вас", "Джарвис запомнит это в профиле. Поменять можно в любой момент.",
      h("div", { class: "card bracket" }, field("Как обращаться", address, "«сэр», «мэм», имя"), field("Город для погоды", city), field("Режим слуха", mode)),
      nav());
  }

  async function finish(): Promise<void> {
    await api("/api/settings", { method: "PUT", body: { wizard_done: true } });
    onDone();
  }

  go(0);
  return root;
}
