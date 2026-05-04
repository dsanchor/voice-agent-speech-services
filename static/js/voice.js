/**
 * voice.js — Streaming voice capture, WebSocket transport, and TTS playback.
 *
 * Audio is captured at 16 kHz 16-bit mono PCM via ScriptProcessorNode and
 * streamed continuously as base64 chunks over a JSON WebSocket.
 */

// ── DOM refs ──────────────────────────────────────────────────────────
const micBtn          = document.getElementById("mic-btn");
const stopSpeakBtn    = document.getElementById("stop-speaking-btn");
const clearBtn        = document.getElementById("clear-btn");
const statusText      = document.getElementById("status-text");
const connDot         = document.getElementById("conn-dot");
const connLabel       = document.getElementById("conn-label");
const partialEl       = document.getElementById("partial-transcript");
const chatHistory     = document.getElementById("chat-history");

// ── State ─────────────────────────────────────────────────────────────
let ws               = null;
let audioCtx         = null;
let mediaStream      = null;
let processor        = null;
let source           = null;
let isMicActive      = false;
let isPlaying        = false;

// Audio playback queue
let playbackQueue    = [];
let playbackCtx      = null;
let currentSource    = null;

// ── WebSocket ─────────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/voice`);

  ws.addEventListener("open", () => {
    connDot.classList.add("connected");
    connLabel.textContent = "Connected";
    micBtn.disabled = false;
    setStatus("Ready — click Start Microphone to begin");
  });

  ws.addEventListener("close", () => {
    connDot.classList.remove("connected");
    connLabel.textContent = "Disconnected";
    micBtn.disabled = true;
    if (isMicActive) stopMic();
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

    case "recognizing":
      partialEl.textContent = msg.text;
      break;

    case "recognized":
      partialEl.textContent = "";
      addChatMessage("user", msg.text);
      break;

    case "agent_response":
      addChatMessage("agent", msg.text);
      break;

    case "tts_audio":
      queueAudio(msg.data);
      break;

    case "tts_end":
      // All audio chunks received
      stopSpeakBtn.disabled = playbackQueue.length === 0 && !isPlaying;
      break;

    case "stop_playback":
      // Server-initiated barge-in: user started speaking
      stopPlayback();
      break;

    case "error":
      setStatus(`⚠️ ${msg.message}`);
      break;

    default:
      console.warn("Unknown message type:", msg.type);
  }
}

// ── Microphone control ────────────────────────────────────────────────

micBtn.addEventListener("click", async () => {
  if (isMicActive) {
    stopMic();
  } else {
    await startMic();
  }
});

async function startMic() {
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

  audioCtx = new AudioContext({ sampleRate: 16000 });
  source = audioCtx.createMediaStreamSource(mediaStream);

  // ScriptProcessorNode sends audio chunks every ~256ms at 4096 samples/16kHz
  processor = audioCtx.createScriptProcessor(4096, 1, 1);

  processor.onaudioprocess = (e) => {
    if (!isMicActive) return;
    const float32 = e.inputBuffer.getChannelData(0);
    // Convert float32 → int16 PCM
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    // Send as base64
    const b64 = arrayBufferToBase64(int16.buffer);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "audio", data: b64 }));
    }
  };

  source.connect(processor);
  processor.connect(audioCtx.destination);

  isMicActive = true;
  micBtn.classList.add("active");
  micBtn.setAttribute("aria-label", "Stop Microphone");

  // Tell server to start continuous recognition
  ws.send(JSON.stringify({ type: "start_mic" }));
}

function stopMic() {
  isMicActive = false;
  micBtn.classList.remove("active");
  micBtn.setAttribute("aria-label", "Start Microphone");
  partialEl.textContent = "";

  if (processor) {
    processor.disconnect();
    processor = null;
  }
  if (source) {
    source.disconnect();
    source = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
  if (audioCtx) {
    audioCtx.close();
    audioCtx = null;
  }

  // Tell server to stop recognition
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop_mic" }));
  }
}

// ── Stop Speaking ─────────────────────────────────────────────────────

stopSpeakBtn.addEventListener("click", () => {
  stopPlayback();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop_speaking" }));
  }
});

function stopPlayback() {
  playbackQueue = [];
  if (currentSource) {
    try { currentSource.stop(); } catch (_) {}
    currentSource = null;
  }
  isPlaying = false;
  stopSpeakBtn.disabled = true;
}

// ── Clear Chat ────────────────────────────────────────────────────────

clearBtn.addEventListener("click", () => {
  chatHistory.innerHTML = "";
  partialEl.textContent = "";
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "clear_chat" }));
  }
});

// ── Audio playback queue ──────────────────────────────────────────────

function queueAudio(base64Data) {
  playbackQueue.push(base64Data);
  stopSpeakBtn.disabled = false;
  if (!isPlaying) {
    playNext();
  }
}

async function playNext() {
  if (playbackQueue.length === 0) {
    isPlaying = false;
    stopSpeakBtn.disabled = true;
    return;
  }

  isPlaying = true;
  const b64 = playbackQueue.shift();

  try {
    if (!playbackCtx || playbackCtx.state === "closed") {
      playbackCtx = new AudioContext();
    }
    const raw = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buffer = await playbackCtx.decodeAudioData(raw.buffer.slice(0));
    currentSource = playbackCtx.createBufferSource();
    currentSource.buffer = buffer;
    currentSource.connect(playbackCtx.destination);
    currentSource.onended = () => {
      currentSource = null;
      playNext();
    };
    currentSource.start();
  } catch (err) {
    console.error("Playback error:", err);
    currentSource = null;
    playNext(); // Skip failed chunk
  }
}

// ── Chat history ──────────────────────────────────────────────────────

function addChatMessage(role, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;

  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = role === "user" ? "You" : "Agent";

  const body = document.createElement("div");
  body.textContent = text;

  div.appendChild(label);
  div.appendChild(body);
  chatHistory.appendChild(div);

  // Auto-scroll to bottom
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

// ── Helpers ───────────────────────────────────────────────────────────

function setStatus(text) {
  statusText.textContent = text;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  // Process in chunks to avoid call stack overflow on large buffers
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

// ── Boot ──────────────────────────────────────────────────────────────
connectWS();
