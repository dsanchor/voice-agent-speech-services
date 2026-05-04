/**
 * audio.js — Audio capture and playback utilities for Voice Agent.
 *
 * Capture: 16kHz, 16-bit mono PCM via ScriptProcessorNode.
 * Playback: MP3 chunks decoded with Web Audio API decodeAudioData.
 */

// ── MicCapture ────────────────────────────────────────────────────────

class MicCapture {
  constructor({ sampleRate = 16000, chunkSize = 4096, onAudioChunk }) {
    this.sampleRate = sampleRate;
    this.chunkSize = chunkSize;
    this.onAudioChunk = onAudioChunk;
    this.audioCtx = null;
    this.mediaStream = null;
    this.source = null;
    this.processor = null;
    this.active = false;
  }

  async start() {
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, sampleRate: this.sampleRate },
    });

    this.audioCtx = new AudioContext({ sampleRate: this.sampleRate });
    this.source = this.audioCtx.createMediaStreamSource(this.mediaStream);

    this.processor = this.audioCtx.createScriptProcessor(this.chunkSize, 1, 1);
    this.processor.onaudioprocess = (e) => {
      if (!this.active) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this.onAudioChunk(arrayBufferToBase64(int16.buffer));
    };

    this.source.connect(this.processor);
    this.processor.connect(this.audioCtx.destination);
    this.active = true;
  }

  stop() {
    this.active = false;
    if (this.processor) { this.processor.disconnect(); this.processor = null; }
    if (this.source) { this.source.disconnect(); this.source = null; }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    if (this.audioCtx) { this.audioCtx.close(); this.audioCtx = null; }
  }
}

// ── AudioPlayer ───────────────────────────────────────────────────────

class AudioPlayer {
  constructor() {
    this.queue = [];
    this.playing = false;
    this.ctx = null;
    this.currentSource = null;
  }

  enqueue(base64Data) {
    this.queue.push(base64Data);
    if (!this.playing) this._playNext();
  }

  async _playNext() {
    if (this.queue.length === 0) {
      this.playing = false;
      return;
    }
    this.playing = true;
    const b64 = this.queue.shift();

    try {
      if (!this.ctx || this.ctx.state === "closed") {
        this.ctx = new AudioContext();
      }
      const raw = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const buffer = await this.ctx.decodeAudioData(raw.buffer.slice(0));
      this.currentSource = this.ctx.createBufferSource();
      this.currentSource.buffer = buffer;
      this.currentSource.connect(this.ctx.destination);
      this.currentSource.onended = () => {
        this.currentSource = null;
        this._playNext();
      };
      this.currentSource.start();
    } catch (err) {
      console.error("Playback error:", err);
      this.currentSource = null;
      this._playNext();
    }
  }

  stop() {
    this.queue = [];
    if (this.currentSource) {
      try { this.currentSource.stop(); } catch (_) {}
      this.currentSource = null;
    }
    this.playing = false;
  }

  get isPlaying() {
    return this.playing;
  }
}

// ── Base64 utilities ──────────────────────────────────────────────────

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}
