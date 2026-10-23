/* ============================================================
   Общее состояние окна: профиль, настройки, статус сессии,
   текущий экран. Маленькая шина событий вместо фреймворка.
   ============================================================ */

type Fn = (v: any) => void;

class AppState {
  profile: { id: number; name: string } | null = null;
  settings: Record<string, any> = {};
  status: any = null;
  route = "hud";
  private subs = new Map<string, Set<Fn>>();

  on(ev: string, fn: Fn): () => void {
    if (!this.subs.has(ev)) this.subs.set(ev, new Set());
    this.subs.get(ev)!.add(fn);
    return () => this.subs.get(ev)?.delete(fn);
  }

  emit(ev: string, v?: unknown): void {
    this.subs.get(ev)?.forEach((f) => f(v));
  }
}

export const app = new AppState();

/** Акцентный цвет пользователя → CSS-переменные HUD. */
export function applyAccent(hex: string): void {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return;
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  const root = document.documentElement.style;
  root.setProperty("--hud", hex);
  root.setProperty("--hud-2", `rgb(${Math.round(r * 0.34)}, ${Math.round(g * 0.58)}, ${Math.round(b * 0.62)})`);
  root.setProperty("--hud-3", `rgba(${r}, ${g}, ${b}, .18)`);
  root.setProperty("--bracket", `rgba(${r}, ${g}, ${b}, .5)`);
}
