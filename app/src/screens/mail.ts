/* ============================================================
   Почта: подключение ящиков (IMAP с паролем приложения или Gmail
   по OAuth), правила сортировки, журнал перемещений. Пароли —
   только в хранилище Windows; в базе лишь ссылка на запись.
   ============================================================ */

import { api, link } from "../api";
import { dateTime, field, h, toast } from "../ui";

const CATS = ["Важное", "Работа", "Счета и банки", "Покупки и доставки", "Рассылки", "Соцсети", "Спам"];

export async function mailView(): Promise<HTMLElement> {
  const root = h("div", { class: "page" });
  const render = async () => {
    const [accs, { settings }, moves] = await Promise.all([api("/api/mail/accounts"), api("/api/settings"), api("/api/mail/moves")]);
    const rules: any[] = settings.mail_rules || [];
    const addr = h("input", { class: "input", placeholder: "you@yandex.ru", autocomplete: "email" }) as HTMLInputElement;
    const pass = h("input", { class: "input", type: "password", placeholder: "пароль приложения" }) as HTMLInputElement;
    const host = h("input", { class: "input", placeholder: "определится сам" }) as HTMLInputElement;
    const gAddr = h("input", { class: "input", placeholder: "you@gmail.com" }) as HTMLInputElement;
    const gId = h("input", { class: "input", placeholder: "client_id" }) as HTMLInputElement;
    const gSecret = h("input", { class: "input", type: "password", placeholder: "client_secret" }) as HTMLInputElement;
    const rVal = h("input", { class: "input grow", placeholder: "ivanov@ или «счёт»" }) as HTMLInputElement;
    const rMatch = h("select", { class: "input", style: { width: "130px" } }, h("option", { value: "from" }, "отправитель"),
      h("option", { value: "subject" }, "тема"), h("option", { value: "keyword" }, "слово")) as HTMLSelectElement;
    const rCat = h("select", { class: "input", style: { width: "170px" } }, CATS.map((c) => h("option", null, c))) as HTMLSelectElement;
    const saveRules = () => api("/api/settings", { method: "PUT", body: { mail_rules: rules } }).then(render);

    root.replaceChildren(
      h("div", { class: "page__head" }, h("h1", { class: "page__title" }, "Почта"),
        h("p", { class: "page__note" }, "«Разбери почту», «что важного во входящих», «прочитай письмо от банка», «отмени последнюю сортировку». Содержимое писем классифицируется локально и никуда не уходит.")),
      h("div", { class: "cols" },
        h("div", { class: "card bracket" }, h("h3", null, "Ящики"),
          accs.length ? h("ul", { class: "list" }, accs.map((a: any) => h("li", null,
            h("span", null, a.address, h("div", { class: "meta" }, a.kind === "gmail" ? "Gmail API · OAuth" : `IMAP · ${a.host}`)),
            h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: async () => { await api(`/api/mail/accounts/${a.id}`, { method: "DELETE" }); void render(); } } }, "Отключить"))))
            : h("p", { class: "muted" }, "Ни одного ящика."),
          h("h3", null, "Яндекс, Mail.ru, Gmail и другие — по IMAP"),
          h("p", { class: "muted" }, "Нужен пароль приложения (не основной пароль): Яндекс ID → Безопасность → Пароли приложений; Mail.ru → Безопасность → Пароли для внешних приложений; Google → Безопасность → Пароли приложений."),
          field("Адрес", addr), field("Пароль приложения", pass), field("IMAP-сервер", host),
          h("button", { class: "btn", type: "button", on: { click: async () => {
            try { await api("/api/mail/accounts", { body: { address: addr.value, password: pass.value, host: host.value } }); toast("Ящик подключён"); void render(); }
            catch (e: any) { toast(e.message, true); }
          } } }, "Подключить"),
          h("h3", null, "Gmail через OAuth (необязательно)"),
          h("p", { class: "muted" }, "Создайте в Google Cloud Console OAuth-клиент типа «Desktop app», включите Gmail API. Права — только gmail.modify (читать и перекладывать, без отправки)."),
          field("Адрес Gmail", gAddr), field("Client ID", gId), field("Client secret", gSecret),
          h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => {
            toast("Откроется окно входа Google…");
            try { await api("/api/mail/gmail", { body: { address: gAddr.value, client_id: gId.value, client_secret: gSecret.value } }); toast("Gmail подключён"); void render(); }
            catch (e: any) { toast(e.message, true); }
          } } }, "Войти через Google")),
        h("div", { class: "card" }, h("h3", null, "Правила сортировки"),
          h("p", { class: "muted" }, "Срабатывают раньше нейросети. Голосом: «письма от Иванова — в Работу»."),
          h("ul", { class: "list" }, rules.map((r, i) => h("li", null, h("span", null, `${{ from: "от", subject: "тема", keyword: "слово" }[r.match as "from"]} «${r.value}» → ${r.category}`),
            h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: () => { rules.splice(i, 1); void saveRules(); } } }, "×")))),
          h("form", { class: "row", on: { submit: (e: Event) => { e.preventDefault(); if (!rVal.value.trim()) return; rules.push({ match: rMatch.value, value: rVal.value.trim().toLowerCase(), category: rCat.value }); void saveRules(); } } },
            rMatch, rVal, rCat, h("button", { class: "btn btn--sm", type: "submit" }, "Добавить")),
          h("div", { class: "row" },
            h("button", { class: "btn btn--ghost", type: "button", on: { click: () => link.send({ type: "text", text: "разбери почту" }) } }, "Разобрать сейчас"),
            h("button", { class: "btn btn--ghost", type: "button", on: { click: () => link.send({ type: "text", text: "что важного во входящих" }) } }, "Сводка"),
            h("button", { class: "btn btn--ghost", type: "button", on: { click: () => link.send({ type: "text", text: "отмени последнюю сортировку" }) } }, "Отменить последнюю сортировку"))),
        h("div", { class: "card" }, h("h3", null, "Журнал перемещений"),
          moves.length ? h("table", { class: "tbl" }, h("tbody", null, moves.slice(0, 80).map((m: any) => h("tr", null,
            h("td", null, dateTime(m.ts)), h("td", null, `${m.from_folder} → ${m.to_folder}`),
            h("td", null, h("span", { class: "tag tag--" + (m.undone ? "cancelled" : m.action === "delete" ? "danger" : "done") }, m.undone ? "отменено" : m.action))))))
            : h("p", { class: "muted" }, "Перемещений не было."))));
  };
  await render();
  return root;
}
