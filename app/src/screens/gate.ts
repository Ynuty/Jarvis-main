/* ============================================================
   Вход: выбор профиля → PIN или пароль. Создание профиля,
   импорт из зашифрованного архива. Несколько пользователей
   на одном компьютере — у каждого своя память, почта, корзина.
   ============================================================ */

import { api, setToken } from "../api";
import { field, h, initials, toast } from "../ui";

export interface LoginResult { token: string; profile: { id: number; name: string }; first_run: boolean; }

export function gate(onLogin: (r: LoginResult) => void): HTMLElement {
  const root = h("div", { class: "gate" });
  const inner = h("div", { class: "gate__inner" });
  root.append(inner);
  void showProfiles();

  async function showProfiles(): Promise<void> {
    let profiles: any[] = [];
    try { profiles = await api("/api/profiles"); } catch (e: any) { toast(e.message, true); }
    if (!profiles.length) return showCreate(true);
    inner.replaceChildren(
      h("p", { class: "gate__eyebrow" }, "Stark Industries · локальный интерфейс"),
      h("h1", { class: "gate__title" }, "J.A.R.V.I.S."),
      h("p", { class: "gate__desc" }, "Выберите профиль. Всё — речь, нейросеть и данные — остаётся на этом компьютере."),
      h("div", { class: "profiles" }, profiles.map((p) =>
        h("button", { class: "profile", type: "button", on: { click: () => showLogin(p) } },
          h("span", { class: "avatar" }, p.avatar || initials(p.name)), p.name))),
      h("div", { class: "row" },
        h("button", { class: "btn btn--ghost", type: "button", on: { click: () => showCreate(false) } }, "Новый профиль"),
        h("button", { class: "btn btn--ghost", type: "button", on: { click: showImport } }, "Импорт профиля")));
  }

  function showLogin(p: any): void {
    const input = h("input", { class: "input" + (p.pw_kind === "pin" ? " pin" : ""), type: "password",
      inputmode: p.pw_kind === "pin" ? "numeric" : "text", autocomplete: "current-password",
      placeholder: p.pw_kind === "pin" ? "PIN" : "Пароль", "aria-label": "PIN или пароль" }) as HTMLInputElement;
    const error = h("p", { class: "error" });
    const submit = async (e: Event) => {
      e.preventDefault();
      try {
        const r = await api<LoginResult>("/api/login", { body: { profile_id: p.id, secret: input.value } });
        setToken(r.token);
        onLogin(r);
      } catch (er: any) { error.textContent = er.message; input.select(); }
    };
    inner.replaceChildren(
      h("span", { class: "avatar", style: { width: "84px", height: "84px", fontSize: "32px" } }, p.avatar || initials(p.name)),
      h("h2", { class: "page__title" }, p.name),
      h("form", { class: "card bracket", on: { submit } },
        field(p.pw_kind === "pin" ? "PIN-код" : "Пароль", input), error,
        h("div", { class: "row" },
          h("button", { class: "btn", type: "submit" }, "Войти"),
          h("button", { class: "btn btn--ghost", type: "button", on: { click: showProfiles } }, "Назад"))));
    setTimeout(() => input.focus(), 50);
  }

  function showCreate(first: boolean): void {
    const name = h("input", { class: "input", maxlength: 40, autocomplete: "nickname", placeholder: "Тони" }) as HTMLInputElement;
    const kind = h("select", { class: "input" }, h("option", { value: "pin" }, "PIN-код (4–8 цифр)"),
      h("option", { value: "password" }, "Пароль (от 6 символов)")) as HTMLSelectElement;
    const secret = h("input", { class: "input", type: "password", autocomplete: "new-password" }) as HTMLInputElement;
    const secret2 = h("input", { class: "input", type: "password", autocomplete: "new-password" }) as HTMLInputElement;
    const error = h("p", { class: "error" });
    const submit = async (e: Event) => {
      e.preventDefault();
      if (secret.value !== secret2.value) { error.textContent = "Не совпадает с повтором"; return; }
      try {
        const r = await api("/api/profiles", { body: { name: name.value, secret: secret.value, kind: kind.value } });
        const lr = await api<LoginResult>("/api/login", { body: { profile_id: r.id, secret: secret.value } });
        setToken(lr.token);
        onLogin(lr);
      } catch (er: any) { error.textContent = er.message; }
    };
    inner.replaceChildren(
      h("p", { class: "gate__eyebrow" }, first ? "Первый запуск" : "Новый профиль"),
      h("h1", { class: "gate__title" }, "J.A.R.V.I.S."),
      h("p", { class: "gate__desc" }, "Создайте профиль. PIN или пароль хранится только в виде хеша argon2id — восстановить его нельзя, только сбросить вместе с данными."),
      h("form", { class: "card bracket", on: { submit } },
        field("Как вас зовут", name), field("Способ входа", kind), field("PIN или пароль", secret), field("Повтор", secret2),
        error,
        h("div", { class: "row" },
          h("button", { class: "btn", type: "submit" }, "Создать"),
          first ? null : h("button", { class: "btn btn--ghost", type: "button", on: { click: showProfiles } }, "Назад"),
          first ? h("button", { class: "btn btn--ghost", type: "button", on: { click: showImport } }, "Импорт профиля") : null)));
    setTimeout(() => name.focus(), 50);
  }

  function showImport(): void {
    const file = h("input", { class: "input", type: "file", accept: ".jarvis" }) as HTMLInputElement;
    const pass = h("input", { class: "input", type: "password" }) as HTMLInputElement;
    const error = h("p", { class: "error" });
    const submit = async (e: Event) => {
      e.preventDefault();
      if (!file.files?.[0]) { error.textContent = "Выберите файл архива"; return; }
      const fd = new FormData();
      fd.append("file", file.files[0]);
      fd.append("password", pass.value);
      try { await api("/api/import", { form: fd }); toast("Профиль импортирован. Пароли почты нужно ввести заново."); void showProfiles(); }
      catch (er: any) { error.textContent = er.message; }
    };
    inner.replaceChildren(
      h("h2", { class: "page__title" }, "Импорт профиля"),
      h("form", { class: "card bracket", on: { submit } },
        field("Файл .jarvis", file), field("Пароль архива", pass), error,
        h("div", { class: "row" },
          h("button", { class: "btn", type: "submit" }, "Импортировать"),
          h("button", { class: "btn btn--ghost", type: "button", on: { click: showProfiles } }, "Назад"))));
  }

  return root;
}
