/* ============================================================
   Профиль: имя и обращение, аватар, город и часовой пояс,
   адреса доставки, магазин по умолчанию, избранное;
   смена PIN, вход по фразе, экспорт и «удалить все мои данные».
   ============================================================ */

import { api, setToken, shell } from "../api";
import { app } from "../state";
import { field, h, toast } from "../ui";

export async function profileView(onLogout: () => void): Promise<HTMLElement> {
  const { settings: s } = await api("/api/settings");
  const cart = await api("/api/cart");
  const put = (body: object) => api("/api/settings", { method: "PUT", body }).then(() => toast("Сохранено")).catch((e) => toast(e.message, true));

  const inp = (key: string, ph = "") => {
    const i = h("input", { class: "input", value: s[key] ?? "", placeholder: ph }) as HTMLInputElement;
    i.onchange = () => void put({ [key]: i.value.trim() });
    return i;
  };
  const avatar = h("input", { class: "input", maxlength: 2, value: s.avatar || "", placeholder: "🙂 или буквы" }) as HTMLInputElement;
  avatar.onchange = () => void put({ avatar: avatar.value.trim() });

  const shop = h("select", { class: "input" }, h("option", { value: "" }, "— не выбран —"),
    cart.shops.map((x: any) => h("option", { value: x.id, selected: x.id === s.default_shop }, x.title))) as HTMLSelectElement;
  shop.onchange = () => void put({ default_shop: shop.value });

  const listEditor = (key: string, title: string, ph: string) => {
    const items: string[] = [...(s[key] || [])];
    const ul = h("ul", { class: "list" });
    const input = h("input", { class: "input grow", placeholder: ph }) as HTMLInputElement;
    const render = () => ul.replaceChildren(...items.map((it, i) => h("li", null, h("span", null, it),
      h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: () => { items.splice(i, 1); void put({ [key]: items }); render(); } } }, "×"))));
    render();
    return h("div", { class: "card" }, h("h3", null, title), ul,
      h("form", { class: "row", on: { submit: (e: Event) => { e.preventDefault(); if (!input.value.trim()) return; items.push(input.value.trim()); input.value = ""; void put({ [key]: items }); render(); } } },
        input, h("button", { class: "btn btn--sm", type: "submit" }, "Добавить")));
  };

  // смена PIN
  const oldS = h("input", { class: "input", type: "password" }) as HTMLInputElement;
  const newS = h("input", { class: "input", type: "password" }) as HTMLInputElement;
  const kind = h("select", { class: "input" }, h("option", { value: "pin" }, "PIN"), h("option", { value: "password" }, "Пароль")) as HTMLSelectElement;
  const phrase = h("input", { class: "input", placeholder: "например: «у лукоморья дуб зелёный»" }) as HTMLInputElement;
  const expPass = h("input", { class: "input", type: "password", placeholder: "пароль архива, от 6 символов" }) as HTMLInputElement;
  const wipePass = h("input", { class: "input", type: "password", placeholder: "ваш PIN или пароль" }) as HTMLInputElement;

  return h("div", { class: "page" },
    h("div", { class: "page__head" }, h("h1", { class: "page__title" }, "Профиль"), h("p", { class: "page__note" }, app.profile?.name)),
    h("div", { class: "cols" },
      h("div", { class: "card bracket" }, h("h3", null, "Вы"),
        field("Как обращаться", inp("address_as", "сэр")), field("Аватар", avatar),
        field("Город (для погоды)", inp("city", "Москва")), field("Часовой пояс", inp("timezone", "Europe/Moscow")),
        field("Магазин по умолчанию", shop)),
      listEditor("addresses", "Адреса доставки", "ул. Ленина, 1, кв. 5"),
      listEditor("favorites", "Избранные позиции", "молоко 3,2% «Простоквашино»"),
      h("div", { class: "card" }, h("h3", null, "Вход"),
        field("Текущий PIN или пароль", oldS), field("Новый", newS), field("Тип", kind),
        h("button", { class: "btn", type: "button", on: { click: async () => {
          try { await api("/api/me/secret", { body: { old: oldS.value, new: newS.value, kind: kind.value } }); toast("Изменено"); oldS.value = newS.value = ""; }
          catch (e: any) { toast(e.message, true); }
        } } }, "Сменить"),
        field("Вход по голосовой фразе (необязательно)", phrase, "Хранится только хеш фразы. Это удобство, а не защита: фразу могут подслушать."),
        h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => {
          await api("/api/me/voice-phrase", { body: { phrase: phrase.value } }); toast(phrase.value ? "Фраза сохранена" : "Вход по фразе выключен");
        } } }, "Сохранить фразу")),
      h("div", { class: "card" }, h("h3", null, "Экспорт и удаление"),
        h("p", { class: "muted" }, "Экспорт — один зашифрованный файл (scrypt + AES-GCM): память, задачи, заметки, история, документы, настройки. Пароли почты в архив не попадают."),
        field("Пароль архива", expPass),
        h("button", { class: "btn", type: "button", on: { click: async () => {
          try {
            const data = await api<ArrayBuffer>("/api/me/export", { body: { password: expPass.value }, raw: true });
            const name = `jarvis-${app.profile?.name}.jarvis`;
            if (shell) { if (await shell.saveFile(name, data)) toast("Сохранено"); }
            else { const a = h("a", { href: URL.createObjectURL(new Blob([data])), download: name }); a.click(); }
          } catch (e: any) { toast(e.message, true); }
        } } }, "Экспортировать"),
        h("p", { class: "muted" }, "«Удалить все мои данные» стирает профиль, память, историю, журнал, корзину, документы и пароли почты из хранилища Windows. Отменить нельзя."),
        field("Подтвердите PIN или паролем", wipePass),
        h("button", { class: "btn btn--danger", type: "button", on: { click: async () => {
          if (!confirm("Удалить профиль и все данные без возможности восстановления?")) return;
          try { await api("/api/me/wipe", { body: { secret: wipePass.value } }); setToken(""); onLogout(); }
          catch (e: any) { toast(e.message, true); }
        } } }, "Удалить все мои данные"),
        h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => { await api("/api/logout", { body: {} }); setToken(""); onLogout(); } } }, "Выйти из профиля"))));
}
