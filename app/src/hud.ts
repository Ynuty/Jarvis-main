/* ============================================================
   HUD — реактор на canvas (перенос из прототипа) + кольцо дня
   из макета «Орбита»: внешнее кольцо — сутки, полночь сверху,
   пройденная часть закрашена, точки на кольце — задачи
   (полые — впереди, залитые — сделаны, золотые — просрочены).
   Состояния: boot · idle · listen · think · speak · confirm · error · sleep.
   ============================================================ */

import * as AudioKit from "./audio";

export type HudState = "boot" | "idle" | "listen" | "think" | "speak" | "confirm" | "error" | "sleep";

export interface DayTask { due_at: number | null; status: string; title: string; }

const PALETTE: Record<HudState, number[]> = {
  boot: [30, 90, 115],
  idle: [47, 167, 200],
  listen: [90, 217, 255],
  think: [255, 176, 58],
  speak: [175, 244, 255],
  confirm: [255, 176, 58],
  error: [255, 90, 77],
  sleep: [34, 74, 92],
};

let cv: HTMLCanvasElement;
let c: CanvasRenderingContext2D;
let W = 0, H = 0, dpr = 1;
let state: HudState = "boot";
const col = PALETTE.boot.slice();
let last = performance.now();
let reveal = 1, revealing = false;
let speakEnv = 0;
let spin = 0, spin2 = 0, sweep = 0, breath = 0;
const ripples: number[] = [];
let rippleClock = 0;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
let running = false;
let tasks: DayTask[] = [];
export let statusText = "";
export const setStatusText = (s: string) => { statusText = s; };

const rgba = (a: number, rgb = col) => `rgba(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0},${a})`;

function resize(): void {
  const box = cv.parentElement!.getBoundingClientRect();
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  W = Math.max(160, box.width);
  H = Math.max(160, cv.clientHeight || box.height);
  cv.width = W * dpr;
  cv.height = H * dpr;
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
}

export function init(canvas: HTMLCanvasElement): void {
  cv = canvas;
  c = cv.getContext("2d")!;
  resize();
  new ResizeObserver(resize).observe(cv.parentElement!);
  if (!running) { running = true; requestAnimationFrame(frame); }
}

export function setState(s: HudState): void { if (PALETTE[s]) state = s; }
export const getState = () => state;
export function revealIn(): void { reveal = 0; revealing = true; }
export function speechPulse(v = 1): void { speakEnv = Math.min(1, speakEnv + 0.45 * v); }
export function setTasks(t: DayTask[]): void { tasks = t; }

/** Попадание клика в центральную «кнопку» реактора. */
export function hitCore(x: number, y: number): boolean {
  const R = radius();
  return Math.hypot(x - W / 2, y - H / 2) < R * 0.55;
}

function radius(): number { return Math.min(W, H) / 2 - 48; }

// ---------- слои ----------

function ringTicks(R: number, count: number, len: number, width: number, rot: number, alpha: number): void {
  c.save();
  c.rotate(rot);
  c.lineWidth = width;
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2;
    if (Math.abs(Math.sin(a * 2)) < 0.06) continue;      // разрывы «на осях»
    const long = i % 8 === 0;
    const l = long ? len * 2.2 : len;
    c.strokeStyle = rgba(long ? alpha : alpha * 0.5);
    c.beginPath();
    c.moveTo(Math.cos(a) * R, Math.sin(a) * R);
    c.lineTo(Math.cos(a) * (R + l), Math.sin(a) * (R + l));
    c.stroke();
  }
  c.restore();
}

function ringArcs(R: number, rot: number, width: number, alpha: number, segs = 3, fill = 0.22): void {
  c.save();
  c.rotate(rot);
  c.lineWidth = width;
  c.lineCap = "round";
  c.strokeStyle = rgba(alpha);
  c.shadowBlur = 18;
  c.shadowColor = rgba(alpha * 0.8);
  for (let i = 0; i < segs; i++) {
    const from = (i / segs) * Math.PI * 2;
    c.beginPath();
    c.arc(0, 0, R, from, from + Math.PI * 2 * fill);
    c.stroke();
  }
  c.restore();
}

function dataRing(R: number, level: number, spectrum: Uint8Array | null): void {
  const BARS = 72;
  c.save();
  c.lineWidth = 2;
  for (let i = 0; i < BARS; i++) {
    const half = i < BARS / 2 ? i : BARS - 1 - i;      // симметрия
    let amp: number;
    if (spectrum && spectrum.length) {
      const bin = 3 + Math.floor((half / (BARS / 2)) * 64);
      amp = (spectrum[bin] || 0) / 255;
    } else amp = 0.25 + 0.25 * Math.sin(half * 0.7 + spin * 6);
    amp = amp * (0.35 + level * 1.4) + speakEnv * 0.5 * (0.4 + 0.6 * Math.sin(half * 0.9 + spin * 9));
    const len = 4 + Math.min(1.15, amp) * R * 0.42;
    const a = (i / BARS) * Math.PI * 2 - Math.PI / 2;
    c.strokeStyle = rgba(0.25 + Math.min(0.6, amp * 0.8));
    c.beginPath();
    c.moveTo(Math.cos(a) * R, Math.sin(a) * R);
    c.lineTo(Math.cos(a) * (R + len), Math.sin(a) * (R + len));
    c.stroke();
  }
  c.restore();
}

function core(R: number, level: number): void {
  const pulse = 1 + Math.sin(breath) * (state === "think" ? 0.12 : 0.05) + level * 0.30 + speakEnv * 0.18;
  const r = R * pulse;
  const g = c.createRadialGradient(0, 0, 0, 0, 0, r);
  g.addColorStop(0, `rgba(255,255,255,${0.85 + level * 0.15})`);
  g.addColorStop(0.35, rgba(0.75));
  g.addColorStop(1, rgba(0));
  c.fillStyle = g;
  c.beginPath();
  c.arc(0, 0, r, 0, Math.PI * 2);
  c.fill();

  c.save();                                              // треугольник реактора
  c.rotate(-Math.PI / 2 + Math.sin(breath * 0.5) * 0.04);
  c.strokeStyle = `rgba(255,255,255,${0.5 + level * 0.4})`;
  c.lineWidth = 1.4;
  c.lineJoin = "round";
  c.beginPath();
  for (let i = 0; i < 3; i++) {
    const a = (i / 3) * Math.PI * 2, rr = R * 0.62 * pulse;
    if (i) c.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); else c.moveTo(Math.cos(a) * rr, Math.sin(a) * rr);
  }
  c.closePath();
  c.stroke();
  c.restore();

  c.strokeStyle = rgba(0.55);
  c.lineWidth = 1;
  c.beginPath();
  c.arc(0, 0, R * 1.28, 0, Math.PI * 2);
  c.stroke();
}

function sweepWedge(R: number): void {
  c.save();
  c.rotate(sweep);
  const g = c.createLinearGradient(0, 0, R, 0);
  g.addColorStop(0, rgba(0));
  g.addColorStop(1, rgba(0.2));
  c.fillStyle = g;
  c.beginPath();
  c.moveTo(0, 0);
  c.arc(0, 0, R, -0.42, 0);
  c.closePath();
  c.fill();
  c.restore();
}

/** «Слушаю»: от кнопки расходятся круги (состояние из PDF). */
function drawRipples(R: number, dt: number): void {
  if (state === "listen") {
    rippleClock += dt;
    if (rippleClock > 0.9) { rippleClock = 0; ripples.push(0); }
  }
  c.save();
  for (let i = ripples.length - 1; i >= 0; i--) {
    ripples[i] += dt * 0.55;
    const p = ripples[i];
    if (p >= 1) { ripples.splice(i, 1); continue; }
    c.strokeStyle = rgba(0.45 * (1 - p));
    c.lineWidth = 1.5;
    c.beginPath();
    c.arc(0, 0, R * (0.25 + p * 0.55), 0, Math.PI * 2);
    c.stroke();
  }
  c.restore();
}

/** Кольцо дня: сутки по кругу, полночь сверху, точки — задачи. */
function dayRing(R: number): void {
  const now = new Date();
  const start = new Date(now); start.setHours(0, 0, 0, 0);
  const frac = (now.getTime() - start.getTime()) / 86400000;
  const top = -Math.PI / 2;
  c.save();
  c.lineCap = "butt";
  c.setLineDash([10, 7]);
  c.lineWidth = 3;
  c.strokeStyle = "rgba(42, 49, 60, .9)";
  c.beginPath(); c.arc(0, 0, R, top + frac * Math.PI * 2, top + Math.PI * 2); c.stroke();
  c.strokeStyle = rgba(0.85);
  c.beginPath(); c.arc(0, 0, R, top, top + frac * Math.PI * 2); c.stroke();
  c.setLineDash([]);

  // метки 6/12/18/24
  c.fillStyle = rgba(0.45);
  c.font = '400 9px "JetBrains Mono", monospace';
  c.textAlign = "center"; c.textBaseline = "middle";
  [["0", 0], ["6", 0.25], ["12", 0.5], ["18", 0.75]].forEach(([t, f]) => {
    const a = top + (f as number) * Math.PI * 2;
    c.fillText(String(t), Math.cos(a) * (R + 14), Math.sin(a) * (R + 14));
  });

  const nowSec = now.getTime() / 1000;
  for (const t of tasks) {
    if (!t.due_at) continue;
    const f = (t.due_at * 1000 - start.getTime()) / 86400000;
    if (f < 0 || f > 1) continue;
    const a = top + f * Math.PI * 2;
    const x = Math.cos(a) * R, y = Math.sin(a) * R;
    c.beginPath();
    c.arc(x, y, 5, 0, Math.PI * 2);
    if (t.status === "done") { c.fillStyle = rgba(0.95); c.fill(); }
    else if (t.due_at < nowSec) { c.fillStyle = "rgba(255,176,58,.95)"; c.fill(); }
    else { c.fillStyle = "rgba(4,8,13,1)"; c.fill(); c.strokeStyle = rgba(0.85); c.lineWidth = 1.5; c.stroke(); }
  }
  // «сейчас»
  const a = top + frac * Math.PI * 2;
  c.beginPath();
  c.arc(Math.cos(a) * R, Math.sin(a) * R, 3.5, 0, Math.PI * 2);
  c.fillStyle = "#fff";
  c.fill();
  c.restore();
}

function label(angle: number, title: string, value: string, R: number): void {
  const right = Math.cos(angle) > 0;
  const x1 = Math.cos(angle) * R, y1 = Math.sin(angle) * R;
  const x2 = Math.cos(angle) * (R + 18), y2 = Math.sin(angle) * (R + 18);
  const x3 = x2 + (right ? 24 : -24);
  c.strokeStyle = rgba(0.4);
  c.lineWidth = 1;
  c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.lineTo(x3, y2); c.stroke();
  c.textAlign = right ? "left" : "right";
  c.textBaseline = "alphabetic";
  const px = x3 + (right ? 7 : -7);
  c.fillStyle = rgba(0.55);
  c.font = '600 9px "Jura", system-ui, sans-serif';
  c.fillText(title.toUpperCase(), px, y2 - 5);
  c.fillStyle = rgba(0.95);
  c.font = '400 11px "JetBrains Mono", ui-monospace, monospace';
  c.fillText(value, px, y2 + 10);
}

// ---------- цикл ----------

function frame(now: number): void {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;

  const target = PALETTE[state] || PALETTE.idle;
  for (let i = 0; i < 3; i++) col[i] += (target[i] - col[i]) * Math.min(1, dt * 6);

  const level = AudioKit.tick();
  speakEnv = Math.max(speakEnv, AudioKit.getOutLevel());
  const mult = reduced ? 0.25 : 1;
  const active = state === "listen" || state === "think" || state === "speak";
  spin += dt * (0.06 + (active ? 0.16 : 0)) * mult;
  spin2 -= dt * (0.10 + (state === "think" ? 0.55 : 0)) * mult;
  sweep += dt * (state === "think" ? 3.4 : 0.5) * mult;
  breath += dt * (state === "speak" ? 4.2 : state === "think" ? 3.0 : 1.5);
  speakEnv *= Math.pow(0.02, dt);
  if (revealing) { reveal = Math.min(1, reveal + dt * 0.9); if (reveal >= 1) revealing = false; }

  c.clearRect(0, 0, W, H);
  c.save();
  c.translate(W / 2, H / 2);
  const R = radius();
  if (R < 40) { c.restore(); return; }
  c.globalAlpha = (revealing ? reveal : 1) * (state === "sleep" ? 0.35 : 1);

  const halo = c.createRadialGradient(0, 0, R * 0.1, 0, 0, R * 1.5);
  halo.addColorStop(0, rgba(0.16 + level * 0.2));
  halo.addColorStop(1, rgba(0));
  c.fillStyle = halo;
  c.fillRect(-W / 2, -H / 2, W, H);

  if (state === "think") sweepWedge(R * 0.98);
  dayRing(R + 22);
  ringTicks(R * 0.99, 120, 5, 1, spin, 0.6);
  ringArcs(R * 0.88, spin2, 2.5, 0.75, 3, 0.24);
  ringArcs(R * 0.80, -spin2 * 0.6, 1, 0.4, 5, 0.10);
  c.strokeStyle = rgba(0.22);
  c.lineWidth = 1;
  c.beginPath(); c.arc(0, 0, R * 0.72, 0, Math.PI * 2); c.stroke();
  drawRipples(R, dt * mult);
  dataRing(R * 0.46, level, state === "listen" ? AudioKit.getSpectrum() : null);
  core(R * 0.20, level);

  if (W > 520 && reveal > 0.6) {               // подписи — только настоящие показатели
    label(-Math.PI * 0.78, "сигнал", String(Math.round(level * 100)).padStart(2, "0") + "%", R * 0.9);
    label(-Math.PI * 0.22, "канал", "RU · 01", R * 0.9);
    label(Math.PI * 0.22, "режим", statusText || "—", R * 0.9);
    label(Math.PI * 0.78, "ядро", state.toUpperCase(), R * 0.9);
  }
  c.restore();
}
