/* ============================================================
   Мелкие помощники DOM: h() вместо фреймворка, уведомления,
   форматирование дат и чисел по-русски.
   ============================================================ */

type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, unknown> & { class?: string; on?: Record<string, (e: any) => void> };

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs | null = null, ...kids: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "on") {
        for (const [ev, fn] of Object.entries(v as Record<string, (e: Event) => void>)) el.addEventListener(ev, fn);
      } else if (k === "class") {
        el.className = String(v);
      } else if (k === "style" && typeof v === "object") {
        Object.assign(el.style, v);
      } else if (k in el && typeof v !== "string") {
        (el as any)[k] = v;
      } else {
        el.setAttribute(k, v === true ? "" : String(v));
      }
    }
  }
  append(el, kids);
  return el;
}

function append(el: Node, kids: Child[]): void {
  for (const k of kids) {
    if (k === null || k === undefined || k === false) continue;
    if (Array.isArray(k)) append(el, k);
    else el.appendChild(typeof k === "object" ? k : document.createTextNode(String(k)));
  }
}

export const $ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector(sel) as T;

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

let toasts: HTMLElement | null = null;
export function toast(text: string, bad = false, ms = 4200): void {
  if (!toasts) {
    toasts = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toasts);
  }
  const t = h("div", { class: "toast" + (bad ? " toast--bad" : "") }, text);
  toasts.append(t);
  setTimeout(() => t.remove(), ms);
}

export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(Math.round(n)) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

const pad = (n: number) => String(n).padStart(2, "0");
export const hhmm = (ts: number) => { const d = new Date(ts * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
export const hhmmss = (d = new Date()) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
export const dateTime = (ts: number) => {
  const d = new Date(ts * 1000);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const clockFromSec = (s: number) => [Math.floor(s / 3600), Math.floor(s / 60) % 60, Math.floor(s % 60)].map(pad).join(":");

const DAYS = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
export const longDate = (d = new Date()) => `${DAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;

export const RISK_TITLE: Record<string, string> = {
  read: "чтение", local: "локально", open: "открыть", external: "снаружи", danger: "необратимо",
};
export const STATUS_TITLE: Record<string, string> = {
  planned: "план", confirmed: "подтверждено", done: "сделано", failed: "сбой", cancelled: "отменено", denied: "запрещено",
};

export function field(label: string, input: HTMLElement, hint?: string): HTMLElement {
  return h("label", { class: "field" }, h("span", null, label), input, hint ? h("small", null, hint) : null);
}

export function initials(name: string): string {
  return name.trim().split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
}
