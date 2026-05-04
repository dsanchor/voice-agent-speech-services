/**
 * config.js — Configuration page logic for Voice Agent.
 */

const STORAGE_KEY = "voiceAgentConfig";

const MANDATORY_FIELDS = [
  "speechRegion",
  "speechResourceId",
  "foundryEndpoint",
  "foundryProject",
  "foundryAgentName",
];

const ALL_FIELDS = [
  ...MANDATORY_FIELDS,
  "foundryApiVersion",
  "ttsOutputFormat",
  "sttLanguage",
  "sttLocales",
  "ttsVoice",
  "enableProactiveGreeting",
  "proactiveGreetingText",
];

const CHECKBOX_FIELDS = ["enableProactiveGreeting"];

// ── DOM refs ──────────────────────────────────────────────────────────
const form = document.getElementById("config-form");
const loadBtn = document.getElementById("load-btn");
const fileInput = document.getElementById("file-input");
const toggleBtn = document.getElementById("toggle-advanced");
const advancedFields = document.getElementById("advanced-fields");

// ── Init: load saved config into form ─────────────────────────────────
(function init() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const cfg = JSON.parse(saved);
      populateForm(cfg);
    } catch (_) {}
  }
})();

// ── Collapsible advanced section ──────────────────────────────────────
toggleBtn.addEventListener("click", () => {
  const hidden = advancedFields.classList.toggle("hidden");
  toggleBtn.querySelector(".toggle-icon").textContent = hidden ? "▶" : "▼";
});

// ── Load Settings from JSON file ──────────────────────────────────────
loadBtn.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (evt) => {
    try {
      const cfg = JSON.parse(evt.target.result);
      populateForm(cfg);
      showToast("Settings loaded from file", "success");
    } catch (err) {
      showToast("Invalid JSON file", "error");
    }
  };
  reader.readAsText(file);
  fileInput.value = "";
});

// ── Form submission ───────────────────────────────────────────────────
form.addEventListener("submit", (e) => {
  e.preventDefault();

  const cfg = {};
  for (const field of ALL_FIELDS) {
    const el = document.getElementById(field);
    if (!el) continue;
    if (CHECKBOX_FIELDS.includes(field)) {
      cfg[field] = el.checked;
    } else {
      cfg[field] = el.value.trim();
    }
  }

  // Validate mandatory
  for (const field of MANDATORY_FIELDS) {
    if (!cfg[field]) {
      showToast(`"${field}" is required`, "error");
      document.getElementById(field).focus();
      return;
    }
  }

  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
  window.location.href = "/voice.html";
});

// ── Helpers ───────────────────────────────────────────────────────────
function populateForm(cfg) {
  for (const field of ALL_FIELDS) {
    const el = document.getElementById(field);
    if (!el || cfg[field] === undefined) continue;
    if (CHECKBOX_FIELDS.includes(field)) {
      el.checked = !!cfg[field];
    } else {
      el.value = cfg[field];
    }
  }
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
