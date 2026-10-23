/* ============================================================
   Корзина и заказы: текущая корзина с правкой, переход в магазин,
   история заказов («повторить»). Оплату Джарвис не проводит:
   адрес и оплату пользователь подтверждает в самом сервисе.
   ============================================================ */

import { api, link } from "../api";
import { dateTime, h, toast } from "../ui";

export async function cartView(): Promise<HTMLElement> {
  const root = h("div", { class: "page" });
  const render = async () => {
    const d = await api("/api/cart");
    const shops: any[] = d.shops;
    const title = (id: string) => shops.find((s) => s.id === id)?.title || id || "—";
    const items: any[] = d.cart?.items || [];
    const shop = h("select", { class: "input", style: { width: "220px" } }, h("option", { value: "" }, "— магазин —"),
      shops.map((s) => h("option", { value: s.id, selected: s.id === d.cart?.shop }, s.title))) as HTMLSelectElement;
    const save = () => api("/api/cart", { method: "PUT", body: { shop: shop.value, items } }).then(render);
    shop.onchange = () => void save();
    const newItem = h("input", { class: "input grow", placeholder: "сметана 20%" }) as HTMLInputElement;

    root.replaceChildren(
      h("div", { class: "page__head" }, h("h1", { class: "page__title" }, "Корзина"),
        h("p", { class: "page__note" }, "Скажите «закажи из Пятёрочки молоко, хлеб и два десятка яиц» — список появится здесь.")),
      h("div", { class: "cols" },
        h("div", { class: "card bracket" }, h("h3", null, "Текущая корзина"), shop,
          items.length ? h("table", { class: "tbl" }, h("tbody", null, items.map((it, i) => {
            const qty = h("input", { class: "input", type: "number", step: "0.5", min: "0", value: String(it.qty), style: { width: "80px" } }) as HTMLInputElement;
            qty.onchange = () => { it.qty = Number(qty.value) || 1; void save(); };
            return h("tr", null, h("td", null, it.name), h("td", null, qty), h("td", null, it.unit),
              h("td", null, h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: () => { items.splice(i, 1); void save(); } } }, "×")));
          }))) : h("p", { class: "muted" }, "Пусто."),
          h("form", { class: "row", on: { submit: (e: Event) => { e.preventDefault(); if (!newItem.value.trim()) return; items.push({ name: newItem.value.trim(), qty: 1, unit: "шт" }); void save(); } } },
            newItem, h("button", { class: "btn btn--sm", type: "submit" }, "Добавить")),
          h("div", { class: "row" },
            h("button", { class: "btn btn--gold", type: "button", disabled: !items.length || !shop.value, on: { click: async () => {
              const r = await api("/api/cart/checkout", { body: {} }); toast(r.say, !r.ok); void render();
            } } }, "Открыть магазин"),
            h("button", { class: "btn btn--ghost", type: "button", disabled: !items.length, on: { click: () => { items.length = 0; void save(); } } }, "Очистить")),
          h("p", { class: "muted" }, "Джарвис откроет сайт с поиском по каждой позиции (или соберёт корзину в видимом окне браузера, если включена автоматизация в настройках). Адрес и оплату вы подтверждаете сами.")),
        h("div", { class: "card" }, h("h3", null, "Заказы"),
          d.orders.length ? h("ul", { class: "list" }, d.orders.map((o: any) => h("li", null,
            h("span", null, `${title(o.shop)}: ${o.items.map((i: any) => i.name).join(", ")}`, h("div", { class: "meta" }, `${dateTime(o.ts)} · ${o.status}`)),
            h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: async () => {
              await api("/api/cart", { method: "PUT", body: { shop: o.shop, items: o.items } }); void render();
            } } }, "В корзину")))) : h("p", { class: "muted" }, "Заказов ещё не было."))));
  };
  await render();
  link.on("line", (m) => { if (m.intent?.startsWith("order") || m.intent?.startsWith("flow:order")) if (document.body.contains(root)) void render(); });
  return root;
}
