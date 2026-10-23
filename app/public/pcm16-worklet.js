/* AudioWorklet: микрофон (обычно 48 кГц) → 16 кГц PCM16 кадрами по 512 сэмплов для ядра.
   Отдельный файл, а не blob: — CSP окна не разрешает исполнять код из blob-адресов. */
class Pcm16 extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / 16000; this.acc = 0; this.buf = new Int16Array(512); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += 1;
      if (this.acc >= this.ratio) {
        this.acc -= this.ratio;
        const s = Math.max(-1, Math.min(1, ch[i]));
        this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.n === 512) { this.port.postMessage(this.buf.buffer, [this.buf.buffer]); this.buf = new Int16Array(512); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor("pcm16", Pcm16);
