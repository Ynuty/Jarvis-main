/* ============================================================
   Шторка «День» (Ctrl+D или язычок сверху): план на день
   и «Сделано Джарвисом» из журнала. Не закрывает поле ввода.
   ============================================================ */

import { api, link } from "../api";
import * as HUD from "../hud";
import { h, hhmm, longDate, plural, toast } from "../ui";

let sheet: HTMLElement | null = null;
let tongue: HTMLElement | null = null;
let open = false;

export function daySheet(): HTMLElement[] {
  tongue = h("button", { class: "tongue", type: "button", on: { click: () => toggleDaySheet() } }, "День");
  sheet = h("section", { class: "daysheet", "aria-hidden": "true", "aria-label": "День" });
  link.on("day", () => void refresh());
  link.on("journal", () => { if (open) void refresh(); });
  link.on("hello", () => void refresh());
  setInterval(() => void refresh(), 5 * 60 * 1000);
  return [tongue, sheet];
}

export function toggleDaySheet(force?: boolean): void {
  open = force ?? !open;
  sheet?.classList.toggle("is-open", open);
  sheet?.setAttribute("aria-hidden", String(!open));
  if (open) void refresh();
}

async function refresh(): Promise<void> {
  if (!sheet) return;
  let data: any;
  try { data = await api("/api/day"); } catch { return; }
  const tasks: any[] = data.tasks;
  HUD.setTasks(tasks);
  const done = tasks.filter((t) => t.status === "done").length;
  if (tongue) tongue.textContent = `День · ${done} из ${tasks.length} ${plural(tasks.length, "задачи", "задач", "задач")} ˅`;

  const now = Date.now() / 1000;
  const taskRow = (t: any) => h("div", { class: "task" + (t.status === "done" ? " is-done" : t.due_at && t.due_at < now ? " is-late" : "") },
    h("time", null, t.due_at ? hhmm(t.due_at) : "—"),
    h("input", { type: "checkbox", checked: t.status === "done", "aria-label": "Сделано",
      on: { change: (e: Event) => void api(`/api/tasks/${t.id}`, { method: "PUT",
        body: { status: (e.target as HTMLInputElement).checked ? "done" : "open" } }) } }),
    h("span", null, t.title, t.created_by === "assistant" ? h("small", { class: "muted" }, " · от Джарвиса") : null),
    h("button", { class: "iconbtn", type: "button", title: "Убрать", on: { click: () => void api(`/api/tasks/${t.id}`, { method: "DELETE" }) } }, "×"));

  const input = h("input", { class: "ask__input", placeholder: "Добавить задачу голосом или текстом… «созвон в 15:00»" });
  const add = async (e: Event) => {
    e.preventDefault();
    const text = (input as HTMLInputElement).value.trim();
    if (!text) return;
    (input as HTMLInputElement).value = "";
    const r = await api("/api/tasks", { body: { title: text } }).catch((er) => toast(er.message, true));
    if (r && !r.ok) toast(r.say, true);
  };

  sheet.replaceChildren(
    h("div", { class: "daysheet__head" },
      h("h2", { class: "daysheet__date" }, longDate()),
      h("span", { class: "daysheet__count" }, `Сделано ${done} из ${tasks.length}`)),
    h("div", { class: "daysheet__body" },
      h("div", null, h("h3", { class: "panel__sub" }, "План на день"),
        tasks.length ? tasks.map(taskRow) : h("p", { class: "muted" }, "Задач нет. Скажите «добавь задачу …».")),
      h("div", null, h("h3", { class: "panel__sub" }, "Сделано Джарвисом"),
        data.done.length ? data.done.slice(0, 30).map((e: any) => h("div", { class: "done" },
          h("time", null, hhmm(e.ts)), h("span", null, e.summary || e.tool)))
          : h("p", { class: "muted" }, "Каждое действие попадает в журнал."))),
    h("form", { class: "daysheet__foot", on: { submit: add } },
      h("div", { class: "ask" }, input, h("button", { class: "ask__go", type: "submit" }, "+")),
      h("button", { class: "btn btn--ghost", type: "button", on: { click: () => link.send({ type: "text", text: "итог дня" }) } }, "Итог дня"),
      h("button", { class: "btn btn--ghost", type: "button", on: { click: () => toggleDaySheet(false) } }, "Свернуть ˄")));
}
