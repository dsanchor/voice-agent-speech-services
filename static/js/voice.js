/**
 * voice.js — Voice session logic for Voice Agent.
 *
 * Reads config from localStorage, connects to WebSocket /ws/voice,
 * handles mic toggle, audio streaming, and message display.
 */

const STORAGE_KEY = "voiceAgentConfig";

// ── Config check ──────────────────────────────────────────────────────
const config = (() => {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    window.location.href = "/index.html";
    return null;
  }
  try { return JSON.parse(raw); } catch (_) {
    window.location.href = "/index.html";
    return null;
  }
})();

if (!config) throw new Error("No config");

// ── DOM refs ──────────────────────────────────────────────────────────
const connDot = document.getElementById("conn-dot");
const connLabel = document.getElementById("conn-label");
const micBtn = document.getElementById("mic-btn");
const micState = document.getElementById("mic-state");
const transcript = document.getElementById("transcript");
const partialEl = document.getElementById("partial-transcript");
const sessionInfo = document.getElementById("session-info");
const endBtn = document.getElementById("end-btn");

// ── State ─────────────────────────────────────────────────────────────
let ws = null;
let mic = null;
let player = new AudioPlayer();
let micActive = false;
let currentState = "idle"; // idle, listening, processing, speaking
let muteAudio = false; // true after barge-in, cleared on new agent_response

// ── Session info display ──────────────────────────────────────────────
sessionInfo.textContent = `${config.foundryAgentName || "Agent"} · ${config.sttLanguage || "en-US"}`;

// ── WebSocket ─────────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/voice`);

  ws.addEventListener("open", () => {
    connDot.classList.add("connected");
    connLabel.textContent = "Connected";
    micBtn.disabled = false;
    setState("idle");

    // Send config overrides
    const cfgMsg = { type: "config" };
    if (config.sttLanguage) cfgMsg.stt_language = config.sttLanguage;
    if (config.ttsVoice) cfgMsg.tts_voice = config.ttsVoice;
    ws.send(JSON.stringify(cfgMsg));

    // Play proactive greeting if enabled
    playGreeting();
  });

  ws.addEventListener("close", () => {
    connDot.classList.remove("connected");
    connLabel.textContent = "Disconnected";
    micBtn.disabled = true;
    if (micActive) stopMic();
    setState("idle");
    setTimeout(connectWS, 3000);
  });

  ws.addEventListener("error", () => ws.close());

  ws.addEventListener("message", (evt) => {
    const msg = JSON.parse(evt.data);
    handleMessage(msg);
  });
}

function handleMessage(msg) {
  switch (msg.type) {
    case "status":
      // Status updates reflected in mic state label only — no popup
      break;

    case "recognizing":
      partialEl.textContent = msg.text;
      partialEl.classList.add("visible");
      setState("listening");
      break;

    case "recognized":
      partialEl.textContent = "";
      partialEl.classList.remove("visible");
      if (msg.text) addBubble("user", msg.text);
      setState("processing");
      break;

    case "agent_response":
      muteAudio = false; // new response cycle — accept its audio
      addBubble("agent", msg.text);
      break;

    case "tts_audio":
      if (muteAudio) break; // drop stale audio from interrupted response
      player.enqueue(msg.data);
      setState("speaking");
      break;

    case "tts_end":
      if (greetingPending) {
        greetingPending = false;
        setState("idle");
        // Don't auto-start mic — let user activate it manually
      } else if (!player.isPlaying) {
        setState(micActive ? "listening" : "idle");
      }
      break;

    case "stop_playback":
      player.stop();
      setState(micActive ? "listening" : "idle");
      break;

    case "error":
      showToast(`⚠️ ${msg.message}`, "error");
      break;

    default:
      console.warn("Unknown message:", msg.type);
  }
}

// ── Mic control ───────────────────────────────────────────────────────

micBtn.addEventListener("click", async () => {
  if (micActive) {
    stopMic();
  } else {
    await startMic();
  }
});

async function startMic() {
  try {
    mic = new MicCapture({
      sampleRate: 16000,
      chunkSize: 4096,
      onAudioChunk: (b64) => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "audio", data: b64 }));
        }
      },
    });
    await mic.start();
  } catch (err) {
    showToast("Microphone access denied", "error");
    return;
  }

  micActive = true;
  micBtn.classList.add("listening");
  setState("listening");

  // Barge-in: stop playback and tell backend to stop TTS streaming
  muteAudio = true;
  player.stop();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop_speaking" }));
  }

  ws.send(JSON.stringify({ type: "start_mic" }));
}

function stopMic() {
  micActive = false;
  micBtn.classList.remove("listening");
  if (mic) { mic.stop(); mic = null; }
  setState("idle");

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop_mic" }));
  }
}

// ── End session ───────────────────────────────────────────────────────
endBtn.addEventListener("click", () => {
  if (micActive) stopMic();
  player.stop();
  if (ws) ws.close();
  window.location.href = "/index.html";
});

// ── UI helpers ────────────────────────────────────────────────────────

function setState(state) {
  currentState = state;
  micBtn.className = "mic-button " + state;
  const labels = { idle: "Ready", listening: "Listening…", processing: "Processing…", speaking: "Speaking…" };
  micState.textContent = labels[state] || "Ready";
}

function addBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `bubble bubble-${role}`;
  bubble.textContent = text;
  transcript.appendChild(bubble);
  transcript.scrollTop = transcript.scrollHeight;
}

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("fade-out");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── Proactive Greeting ────────────────────────────────────────────────

let greetingPending = false;

function playGreeting() {
  if (config.enableProactiveGreeting === false) return;
  const text = config.proactiveGreetingText || "Hello! How can I help you today?";

  // Show greeting in transcript
  addBubble("agent", text);

  // Send greeting to backend for TTS using the same voice as agent responses
  setState("speaking");
  greetingPending = true;
  ws.send(JSON.stringify({ type: "greeting", text: text }));
}

// After greeting TTS ends, just go idle — don't auto-start mic

// ── Boot ──────────────────────────────────────────────────────────────
connectWS();
