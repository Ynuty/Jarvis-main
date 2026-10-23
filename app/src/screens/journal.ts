/* Журнал действий: каждое действие навыков — что, когда, уровень риска, статус, результат. */

import { api, link } from "../api";
import { dateTime, h, RISK_TITLE, STATUS_TITLE } from "../ui";

export async function journalView(): Promise<HTMLElement> {
  const root = h("div", { class: "page" });
  const filter = h("select", { class: "input", style: { width: "200px" } },
    [["", "Все навыки"], ["desktop", "Рабочий стол"], ["day", "День"], ["order", "Заказы"], ["mail", "Почта"],
     ["notes", "Заметки"], ["memory", "Память"], ["info", "Справка и сеть"], ["timers", "Таймеры"], ["system", "Система"]]
      .map(([v, t]) => h("option", { value: v }, t))) as HTMLSelectElement;
  const body = h("tbody");
  const render = async () => {
    const rows = await api(`/api/journal?limit=300${filter.value ? "&skill=" + filter.value : ""}`);
    body.replaceChildren(...rows.map((e: any) => h("tr", null,
      h("td", null, dateTime(e.ts)),
      h("td", null, e.summary || e.tool, h("div", { class: "meta muted" }, e.tool + (e.source !== "user" && e.source !== "rule" ? " · " + e.source : ""))),
      h("td", null, h("span", { class: "tag tag--" + e.risk }, RISK_TITLE[e.risk] || e.risk)),
      h("td", null, h("span", { class: "tag tag--" + e.status }, STATUS_TITLE[e.status] || e.status)),
      h("td", { class: "muted", style: { maxWidth: "380px", whiteSpace: "pre-wrap" } }, (e.result || "").slice(0, 240)))));
  };
  filter.onchange = () => void render();
  root.append(
    h("div", { class: "page__head" }, h("h1", { class: "page__title" }, "Журнал"),
      h("p", { class: "page__note" }, "Что сделано, когда и с каким риском. Пароли и токены сюда не пишутся."), filter),
    h("div", { class: "card" }, h("table", { class: "tbl" },
      h("thead", null, h("tr", null, ["Когда", "Действие", "Риск", "Статус", "Результат"].map((t) => h("th", null, t)))), body)));
  await render();
  link.on("journal", () => { if (document.body.contains(root)) void render(); });
  return root;
}
