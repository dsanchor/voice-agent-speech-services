/**
 * voice.js — Browser-side voice capture, WebSocket transport, and TTS playback.
 *
 * Audio is captured at 16 kHz 16-bit mono PCM via AudioWorklet, wrapped in a
 * minimal WAV header, and sent as a base64-encoded blob over a JSON WebSocket.
 */

// ── DOM refs ──────────────────────────────────────────────────────────
const recordBtn      = document.getElementById("record-btn");
const statusText     = document.getElementById("status-text");
const connDot        = document.getElementById("conn-dot");
const connLabel      = document.getElementById("conn-label");
const transcriptEl   = document.getElementById("transcript");
const agentReplyEl   = document.getElementById("agent-response");

// ── State ─────────────────────────────────────────────────────────────
let ws               = null;
let audioCtx         = null;
let mediaStream      = null;
let mediaRecorder    = null;
let recordedChunks   = [];
let isRecording      = false;

// ── WebSocket ─────────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/voice`);

  ws.addEventListener("open", () => {
    connDot.classList.add("connected");
    connLabel.textContent = "Connected";
    recordBtn.disabled = false;
    setStatus("Ready — tap the button to speak");
  });

  ws.addEventListener("close", () => {
    connDot.classList.remove("connected");
    connLabel.textContent = "Disconnected";
    recordBtn.disabled = true;
    setStatus("Connection lost — reconnecting…");
    setTimeout(connectWS, 2000);
  });

  ws.addEventListener("error", () => {
    ws.close();
  });

  ws.addEventListener("message", (evt) => {
    const msg = JSON.parse(evt.data);
    handleServerMessage(msg);
  });
}

function handleServerMessage(msg) {
  switch (msg.type) {
    case "status":
      setStatus(msg.message);
      break;

    case "transcript":
      transcriptEl.textContent = msg.text;
      transcriptEl.classList.remove("placeholder");
      break;

    case "agent_response":
      agentReplyEl.textContent = msg.text;
      agentReplyEl.classList.remove("placeholder");
      break;

    case "tts_audio":
      playAudio(msg.data, msg.format);
      break;

    case "error":
      setStatus(`⚠️ ${msg.message}`);
      enableRecording();
      break;

    default:
      console.warn("Unknown message type:", msg.type);
  }
}

// ── Recording ─────────────────────────────────────────────────────────

recordBtn.addEventListener("click", async () => {
  if (isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
});

async function startRecording() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
      },
    });
  } catch (err) {
    setStatus("⚠️ Microphone access denied");
    return;
  }

  // Use AudioContext to resample to 16 kHz PCM
  audioCtx = new AudioContext({ sampleRate: 16000 });
  const source = audioCtx.createMediaStreamSource(mediaStream);

  // ScriptProcessorNode is deprecated but widely supported and simple.
  // A production build should migrate to AudioWorkletNode.
  const processor = audioCtx.createScriptProcessor(4096, 1, 1);
  recordedChunks = [];

  processor.onaudioprocess = (e) => {
    const float32 = e.inputBuffer.getChannelData(0);
    // Convert float32 → int16 PCM
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    recordedChunks.push(int16);
  };

  source.connect(processor);
  processor.connect(audioCtx.destination);

  isRecording = true;
  recordBtn.classList.add("recording");
  setStatus("Listening… tap to stop");
}

function stopRecording() {
  isRecording = false;
  recordBtn.classList.remove("recording");
  recordBtn.disabled = true;

  // Stop mic
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
  if (audioCtx) {
    audioCtx.close();
    audioCtx = null;
  }

  setStatus("Processing…");

  // Merge chunks into a single PCM buffer
  const totalLen = recordedChunks.reduce((n, c) => n + c.length, 0);
  const pcm = new Int16Array(totalLen);
  let offset = 0;
  for (const chunk of recordedChunks) {
    pcm.set(chunk, offset);
    offset += chunk.length;
  }
  recordedChunks = [];

  // Wrap in WAV header for the backend Speech SDK
  const wav = encodeWAV(pcm, 16000);
  const b64 = arrayBufferToBase64(wav);

  ws.send(JSON.stringify({ type: "audio", data: b64 }));
}

// ── Audio playback ────────────────────────────────────────────────────

async function playAudio(base64Data, format) {
  setStatus("Playing response…");
  try {
    const raw = Uint8Array.from(atob(base64Data), (c) => c.charCodeAt(0));
    const playCtx = new AudioContext();
    const buffer = await playCtx.decodeAudioData(raw.buffer);
    const src = playCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(playCtx.destination);
    src.onended = () => {
      enableRecording();
      setStatus("Ready — tap the button to speak");
    };
    src.start();
  } catch (err) {
    console.error("Playback error:", err);
    setStatus("⚠️ Could not play audio");
    enableRecording();
  }
}

// ── Helpers ───────────────────────────────────────────────────────────

function setStatus(text) {
  statusText.textContent = text;
}

function enableRecording() {
  recordBtn.disabled = false;
}

function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/** Encode 16-bit PCM samples into a WAV file ArrayBuffer. */
function encodeWAV(samples, sampleRate) {
  const byteRate = sampleRate * 2; // 16-bit mono
  const blockAlign = 2;
  const dataBytes = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeString(view, 8, "WAVE");

  // fmt sub-chunk
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);           // sub-chunk size
  view.setUint16(20, 1, true);            // PCM format
  view.setUint16(22, 1, true);            // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);           // bits per sample

  // data sub-chunk
  writeString(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  // PCM samples
  const int16View = new Int16Array(buffer, 44);
  int16View.set(samples);

  return buffer;
}

function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

// ── Boot ──────────────────────────────────────────────────────────────
connectWS();
