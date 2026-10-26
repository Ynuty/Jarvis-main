/* ============================================================
   Связь с ядром: REST (fetch) и WebSocket (события + аудио).
   Порт и общий секрет выдаёт оболочка через preload
   (window.jarvisShell). В браузере для разработки — ?port=.
   ============================================================ */

export interface ShellBridge {
  secret: string;
  port: number;
  version: string;
  platform: string;
  notify(title: string, body: string): void;
  setHotkey(accel: string): Promise<boolean>;
  setAutostart(on: boolean): Promise<void>;
  openExternal(url: string): void;
  saveFile(name: string, data: ArrayBuffer): Promise<boolean>;
  onHotkey(cb: () => void): void;
  onTray(cb: (action: string) => void): void;
  showWindow(): void;
  quit(): void;
  coreStatus(): Promise<{ core: string; ollama: string; log: string }>;
}

declare global {
  interface Window { jarvisShell?: ShellBridge; }
}

export const shell = window.jarvisShell;
const qs = new URLSearchParams(location.search);
export const PORT = shell?.port ?? Number(qs.get("port") || 8777);
const SECRET = shell?.secret ?? qs.get("s") ?? "";
export const BASE = `http://127.0.0.1:${PORT}`;

let token = "";
export const setToken = (t: string) => { token = t; };
export const getToken = () => token;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function headers(json = true): Record<string, string> {
  const hd: Record<string, string> = {};
  if (json) hd["Content-Type"] = "application/json";
  if (SECRET) hd["X-Jarvis-Secret"] = SECRET;
  if (token) hd["Authorization"] = "Bearer " + token;
  return hd;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const res = await fetch(BASE + path, {
    method,
    headers: headers(!opts.form),
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* тело не JSON */ }
    // токен живёт в памяти ядра: после его перезапуска он недействителен — назад к входу
    if (res.status === 401 && token && path !== "/api/login") link.emit({ type: "auth_lost" });
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  if (opts.raw) return (await res.arrayBuffer()) as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? await res.json() : await res.text()) as T;
}

/** POST с ответом text/event-stream: прогресс скачивания моделей. */
export async function sse(path: string, body: unknown, onData: (d: any) => void): Promise<void> {
  const res = await fetch(BASE + path, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (res.status === 401 && token) link.emit({ type: "auth_lost" });
  if (!res.ok || !res.body) throw new ApiError(res.status, await res.text());
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (chunk.startsWith("data:")) onData(JSON.parse(chunk.slice(5)));
    }
  }
}

export async function waitCore(tries = 120): Promise<any> {
  for (let i = 0; i < tries; i++) {
    try { return await api("/api/health"); } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error("ядро не отвечает");
}

type Handler = (msg: any) => void;

/** WebSocket с переподключением. Бинарные кадры: вверх — PCM16 микрофона, вниз — WAV озвучки. */
export class Link {
  ws: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private audioHandler: ((buf: ArrayBuffer) => void) | null = null;
  private closed = false;
  private retry = 0;
  connected = false;

  connect(): void {
    this.closed = false;
    const url = `ws://127.0.0.1:${PORT}/ws?token=${encodeURIComponent(token)}${SECRET ? "&s=" + encodeURIComponent(SECRET) : ""}`;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => { this.connected = true; this.retry = 0; this.emit({ type: "link", up: true }); };
    ws.onclose = (e) => {
      this.connected = false;
      this.emit({ type: "link", up: false, code: e.code });
      if (e.code === 4401) { this.emit({ type: "auth_lost" }); return; }
      if (!this.closed) setTimeout(() => this.connect(), Math.min(5000, 400 * ++this.retry));
    };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") this.emit(JSON.parse(e.data));
      else this.audioHandler?.(e.data as ArrayBuffer);
    };
  }

  close(): void { this.closed = true; this.ws?.close(); }

  on(type: string, fn: Handler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)!.add(fn);
    return () => this.handlers.get(type)?.delete(fn);
  }

  onAudio(fn: (buf: ArrayBuffer) => void): void { this.audioHandler = fn; }

  emit(msg: any): void {
    this.handlers.get(msg.type)?.forEach((f) => f(msg));
    this.handlers.get("*")?.forEach((f) => f(msg));
  }

  send(msg: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  sendAudio(buf: ArrayBuffer): void {
    if (this.ws?.readyState === WebSocket.OPEN && this.ws.bufferedAmount < 1 << 20) this.ws.send(buf);
  }
}

export const link = new Link();
