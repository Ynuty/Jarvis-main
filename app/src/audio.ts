/* ============================================================
   AudioKit — микрофон и динамик интерфейса.
   Микрофон: getUserMedia с эхоподавлением Chromium → AudioWorklet
   → 16 кГц PCM16 кадрами по 512 сэмплов → ядро (VAD + Whisper).
   Голос Джарвиса играет здесь же, в том же процессе, поэтому
   эхоподавитель видит его и вычитает из микрофона.
   Уровень сигнала для HUD настоящий (RMS), огибающая речи — с выхода.
   ============================================================ */

const WORKLET_URL = new URL("./pcm16-worklet.js", document.baseURI).href;
let workletLoaded = false;

let ctx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let outAnalyser: AnalyserNode | null = null;
let gain: GainNode | null = null;
let stream: MediaStream | null = null;
let node: AudioWorkletNode | null = null;
let timeData: Uint8Array | null = null;
let spectrum: Uint8Array | null = null;
let outData: Uint8Array | null = null;
let level = 0;
let outLevel = 0;
let streaming = false;
let onFrame: ((b: ArrayBuffer) => void) | null = null;

export function ensureCtx(): AudioContext {
  if (!ctx) {
    ctx = new AudioContext();
    gain = ctx.createGain();
    outAnalyser = ctx.createAnalyser();
    outAnalyser.fftSize = 512;
    gain.connect(outAnalyser).connect(ctx.destination);
    outData = new Uint8Array(outAnalyser.fftSize);
  }
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

/** Просит микрофон. true — анализатор поднялся. */
export async function startMic(deviceId?: string): Promise<boolean> {
  if (analyser && node) return true;
  const ac = ensureCtx();
  let s: MediaStream;
  try {
    s = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
               deviceId: deviceId ? { exact: deviceId } : undefined },
    });
  } catch (e: any) {
    throw new Error(e?.name === "NotAllowedError" ? "доступ к микрофону запрещён"
      : e?.name === "NotFoundError" ? "микрофон не найден" : `микрофон: ${e?.message || e}`);
  }
  try {
    if (!workletLoaded) { await ac.audioWorklet.addModule(WORKLET_URL); workletLoaded = true; }
    const src = ac.createMediaStreamSource(s);
    const an = ac.createAnalyser();
    an.fftSize = 512;
    an.smoothingTimeConstant = 0.72;
    src.connect(an);
    const wn = new AudioWorkletNode(ac, "pcm16");
    wn.port.onmessage = (e) => { if (streaming && onFrame) onFrame(e.data as ArrayBuffer); };
    src.connect(wn);
    // всё поднялось — только теперь фиксируем состояние (раньше половинчатый запуск выглядел как «слушаю»)
    stream = s; analyser = an; node = wn;
    timeData = new Uint8Array(an.fftSize);
    spectrum = new Uint8Array(an.frequencyBinCount);
    return true;
  } catch (e: any) {
    s.getTracks().forEach((t) => t.stop());
    throw new Error(`обработчик звука не загрузился: ${e?.message || e}`);
  }
}

export function stopMic(): void {
  stream?.getTracks().forEach((t) => t.stop());
  node?.disconnect();
  stream = null; analyser = null; node = null; level = 0;
}

export function setStreaming(on: boolean, sink?: (b: ArrayBuffer) => void): void {
  streaming = on;
  if (sink) onFrame = sink;
}

export const hasMic = () => !!analyser;
export const getLevel = () => level;
export const getSpectrum = () => spectrum;
export const getOutLevel = () => outLevel;

/** Каждый кадр HUD: RMS с асимметричным сглаживанием (быстро вверх, медленно вниз). */
export function tick(): number {
  if (analyser && timeData && spectrum) {
    analyser.getByteTimeDomainData(timeData);
    analyser.getByteFrequencyData(spectrum);
    let sum = 0;
    for (let i = 0; i < timeData.length; i++) { const v = (timeData[i] - 128) / 128; sum += v * v; }
    const n = Math.min(1, Math.sqrt(sum / timeData.length) * 4.2);
    level += (n - level) * (n > level ? 0.45 : 0.12);
  } else level *= 0.9;
  if (outAnalyser && outData) {
    outAnalyser.getByteTimeDomainData(outData);
    let sum = 0;
    for (let i = 0; i < outData.length; i++) { const v = (outData[i] - 128) / 128; sum += v * v; }
    const n = Math.min(1, Math.sqrt(sum / outData.length) * 5);
    outLevel += (n - outLevel) * (n > outLevel ? 0.5 : 0.1);
  }
  return level;
}

// ---------- воспроизведение голоса ----------

const queue: { buf?: ArrayBuffer; text?: string; volume: number }[] = [];
// (у WAV-элемента text — подпись фразы, чтобы при сбое сказать её голосом Windows)
let playing = false;
let current: AudioBufferSourceNode | null = null;
let onIdle: (() => void) | null = null;
let onStart: (() => void) | null = null;
let ttsVoice: SpeechSynthesisVoice | null = null;
let rate = 1;

export function onPlayback(start: () => void, idle: () => void): void { onStart = start; onIdle = idle; }
export function setRate(r: number): void { rate = r; }

/** Диагностика звука: смотреть в консоли окна — window.__jarvisAudio */
export const stats = { received: 0, played: 0, webSpeech: 0, errors: 0, lastError: "", ctx: "" };
(window as any).__jarvisAudio = stats;

export function enqueueWav(buf: ArrayBuffer, volume = 1, text = ""): void { stats.received++; queue.push({ buf, volume, text }); void pump(); }
export function enqueueText(text: string, volume = 1): void { queue.push({ text, volume }); void pump(); }

async function pump(): Promise<void> {
  if (playing) return;
  const item = queue.shift();
  if (!item) { onIdle?.(); return; }
  playing = true;
  onStart?.();
  try {
    if (item.buf) { await playWav(item.buf, item.volume); stats.played++; }
    else if (item.text) { await speakWeb(item.text, item.volume); stats.webSpeech++; }
  } catch (e: any) {
    stats.errors++; stats.lastError = String(e?.message || e);
    console.error("озвучка:", e);
    if (item.buf && item.text) { try { await speakWeb(item.text, item.volume); stats.webSpeech++; } catch { /* нет и запасного */ } }
  }
  playing = false;
  void pump();
}

// Браузер может «усыпить» звук до первого действия пользователя — будим при любом клике/клавише.
for (const ev of ["pointerdown", "keydown"]) {
  window.addEventListener(ev, () => { if (ctx && ctx.state !== "running") void ctx.resume(); }, { capture: true });
}

async function playWav(buf: ArrayBuffer, volume: number): Promise<void> {
  const ac = ensureCtx();
  if (ac.state !== "running") await Promise.race([ac.resume(), new Promise((r) => setTimeout(r, 500))]);
  stats.ctx = ac.state;
  if (ac.state !== "running") throw new Error("аудио выключено браузером: " + ac.state);
  const audio = await ac.decodeAudioData(buf.slice(0));
  gain!.gain.value = volume;
  await new Promise<void>((resolve) => {
    const src = ac.createBufferSource();
    src.buffer = audio;
    src.connect(gain!);
    src.onended = () => { current = null; resolve(); };
    current = src;
    src.start();
  });
}

/** Запасной голос — Web Speech API, если в ядре нет TTS. */
function speakWeb(text: string, volume: number): Promise<void> {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth) return resolve();
    if (!ttsVoice) {
      const ru = synth.getVoices().filter((v) => v.lang.toLowerCase().startsWith("ru"));
      ttsVoice = ru.find((v) => /google|pavel|dmitry|yuri/i.test(v.name)) || ru[0] || null;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ru-RU";
    if (ttsVoice) u.voice = ttsVoice;
    u.rate = 1.02 * rate;
    u.pitch = 0.85;
    u.volume = volume;
    u.onend = u.onerror = () => resolve();
    synth.speak(u);
    setTimeout(() => { if (!synth.speaking) resolve(); }, 1500);
  });
}

export function stopPlayback(): void {
  queue.length = 0;
  try { current?.stop(); } catch { /* уже остановлен */ }
  current = null;
  window.speechSynthesis?.cancel();
  playing = false;
  onIdle?.();
}

export const isPlaying = () => playing || queue.length > 0;

// ---------- служебные сигналы ----------

const TONES: Record<string, [number, number][]> = {
  wake: [[880, 0.06], [1320, 0.10]],
  ack: [[660, 0.09]],
  done: [[988, 0.07], [1319, 0.12]],
  error: [[220, 0.16]],
  timer: [[1046, 0.12], [784, 0.12], [1046, 0.18]],
  boot: [[262, 0.10], [392, 0.10], [523, 0.10], [784, 0.22]],
  confirm: [[784, 0.08], [988, 0.08]],
};

export function beep(name: string, scale = 1): void {
  const seq = TONES[name];
  if (!seq) return;
  const ac = ensureCtx();
  let t = ac.currentTime;
  for (const [freq, dur] of seq) {
    const osc = ac.createOscillator();
    const g = ac.createGain();
    osc.type = name === "error" ? "sawtooth" : "sine";
    osc.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.09 * scale, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g).connect(ac.destination);   // мимо gain голоса: не влияет на огибающую речи
    osc.start(t);
    osc.stop(t + dur + 0.02);
    t += dur * 0.85;
  }
}

export async function listMics(): Promise<MediaDeviceInfo[]> {
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter((d) => d.kind === "audioinput");
}
