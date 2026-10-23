/* ============================================================
   Память и знания: факты о пользователе (правка, удаление),
   заметки, документы для поиска (RAG), история диалога.
   ============================================================ */

import { api, link } from "../api";
import { dateTime, h, toast } from "../ui";

const CATS = ["имя", "семья", "предпочтения", "еда", "работа", "дом", "здоровье", "привычки", "покупки", "общее"];

export async function memoryView(): Promise<HTMLElement> {
  const root = h("div", { class: "page" });
  const render = async () => {
    const [facts, notes, docs] = await Promise.all([api("/api/memory"), api("/api/notes"), api("/api/docs")]);
    const factRow = (f: any) => {
      const text = h("input", { class: "input", value: f.fact }) as HTMLInputElement;
      const cat = h("select", { class: "input", style: { width: "140px" } }, CATS.map((c) => h("option", { selected: c === f.category }, c))) as HTMLSelectElement;
      const save = () => void api(`/api/memory/${f.id}`, { method: "PUT", body: { fact: text.value, category: cat.value } }).then(() => toast("Сохранено"));
      text.onchange = cat.onchange = save;
      return h("li", { style: { gridTemplateColumns: "1fr 140px auto" } }, text, cat,
        h("button", { class: "btn btn--sm btn--ghost", type: "button", title: f.source === "extracted" ? "Извлечено из разговора" : "Сказано вами",
          on: { click: async () => { await api(`/api/memory/${f.id}`, { method: "DELETE" }); void render(); } } }, "Забыть"));
    };
    const newFact = h("input", { class: "input grow", placeholder: "Я не ем мясо" }) as HTMLInputElement;
    const file = h("input", { class: "input grow", type: "file", accept: ".txt,.md,.docx,.pdf,.csv" }) as HTMLInputElement;

    root.replaceChildren(
      h("div", { class: "page__head" }, h("h1", { class: "page__title" }, "Память"),
        h("p", { class: "page__note" }, "Только то, что вы сказали сами или что Джарвис извлёк из ваших слов. Всё правится и удаляется.")),
      h("div", { class: "cols" },
        h("div", { class: "card bracket" }, h("h3", null, `Факты о вас · ${facts.length}`),
          h("ul", { class: "list" }, facts.map(factRow)),
          h("form", { class: "row", on: { submit: async (e: Event) => {
            e.preventDefault(); if (!newFact.value.trim()) return;
            await api("/api/memory", { body: { fact: newFact.value, category: "общее" } }); void render();
          } } }, newFact, h("button", { class: "btn btn--sm", type: "submit" }, "Запомнить"))),
        h("div", { class: "card" }, h("h3", null, `Документы для поиска · ${docs.length}`),
          h("p", { class: "muted" }, "Джарвис ищет по ним ответы («в моих документах …»). Файлы режутся на фрагменты и индексируются локально моделью эмбеддингов."),
          h("ul", { class: "list" }, docs.map((d: any) => h("li", null,
            h("span", null, d.title, h("div", { class: "meta" }, `${d.chunks} фрагм. · ${dateTime(d.added_at)}`)),
            h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: async () => { await api(`/api/docs/${d.id}`, { method: "DELETE" }); void render(); } } }, "Убрать")))),
          h("form", { class: "row", on: { submit: async (e: Event) => {
            e.preventDefault(); if (!file.files?.[0]) return;
            const fd = new FormData(); fd.append("file", file.files[0]);
            toast("Индексирую…");
            try { await api("/api/docs", { form: fd }); toast("Документ добавлен"); void render(); } catch (er: any) { toast(er.message, true); }
          } } }, file, h("button", { class: "btn btn--sm", type: "submit" }, "Добавить"))),
        h("div", { class: "card" }, h("h3", null, `Заметки · ${notes.length}`),
          h("ul", { class: "list" }, notes.map((n: any) => h("li", null, h("span", null, n.text, h("div", { class: "meta" }, dateTime(n.at))),
            h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: async () => { await api(`/api/notes/${n.id}`, { method: "DELETE" }); void render(); } } }, "×"))))),
        h("div", { class: "card" }, h("h3", null, "История разговора"),
          h("p", { class: "muted" }, "Последние реплики и их краткое резюме помогают Джарвису держать контекст. Очистка не трогает факты выше."),
          h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => { await api("/api/history", { method: "DELETE" }); toast("История очищена"); } } }, "Очистить историю"))));
  };
  await render();
  link.on("memory", () => { if (document.body.contains(root)) void render(); });
  return root;
}
