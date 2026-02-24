"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let userTimezone = "Asia/Riyadh";
let isBusy = false;
let recognition = null;
let isListening = false;
let continuousMode = false;   // auto-restart voice after each reply
let cameraStream = null;
let autoAnalyze = false;
let autoInterval = null;
let lastCamContext = "";      // injected into chat when camera is on

// ── Audio Engine (Synthesized SFX) ───────────────────────────────────────────
const JARVIS_Audio = {
  ctx: null,
  init() { if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)(); },
  play(freq, type, dur, vol = 0.1) {
    this.init();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.type = type; osc.frequency.setValueAtTime(freq, this.ctx.currentTime);
    g.gain.setValueAtTime(vol, this.ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.00001, this.ctx.currentTime + dur);
    osc.connect(g); g.connect(this.ctx.destination);
    osc.start(); osc.stop(this.ctx.currentTime + dur);
  },
  blip() { this.play(880, 'sine', 0.1, 0.05); },
  chirp() { this.play(1200, 'square', 0.05, 0.02); this.play(1500, 'square', 0.05, 0.02); },
  ui() { this.play(600, 'sine', 0.15, 0.03); },
  confirm() { this.play(800, 'sine', 0.1, 0.05); setTimeout(() => this.play(1200, 'sine', 0.1, 0.05), 50); }
};

// Basic UI
const clkTime = document.getElementById("clk-time");
const clkDate = document.getElementById("clk-date");
const chatArea = document.getElementById("chat-area");

// Menu
const menuTrigger = document.getElementById("menu-trigger");
const lightningTrigger = document.getElementById("lightning-trigger");
const menuItems = document.getElementById("menu-items");
const interruptBtn = document.getElementById("interrupt-btn");

// Camera
const camPanel = document.getElementById("camera-panel");
const camToggleBtn = document.getElementById("cam-toggle-btn");
const camAnalyzeBtn = document.getElementById("cam-analyze-btn");
const camCloseBtn = document.getElementById("cam-close-btn");
const camVideo = document.getElementById("cam-video");
const camCanvas = document.getElementById("cam-canvas");
const camOverlay = document.getElementById("cam-overlay");
const camAutoBtn = document.getElementById("cam-auto-btn");

// Upload
const uploadPanel = document.getElementById("upload-panel");
const uploadToggle = document.getElementById("upload-toggle-btn");
const uploadClose = document.getElementById("upload-close-btn");
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const uploadQ = document.getElementById("upload-question");
const saveFileCb = document.getElementById("save-file-cb");
const uploadStatus = document.getElementById("upload-status");

// Knowledge
const kbPanel = document.getElementById("kb-panel");
const kbBtn = document.getElementById("kb-btn");
const kbClose = document.getElementById("kb-close-btn");
const kbList = document.getElementById("kb-list");

// Continuous / Voice
const continuousBtn = document.getElementById("continuous-btn");
const voiceBtn = document.getElementById("voice-btn");
const voiceOverlay = document.getElementById("voice-overlay");
const voiceLabel = document.getElementById("voice-label");
const stopVoiceBtn = document.getElementById("stop-voice-btn");
const contIndicator = document.getElementById("continuous-indicator");

// Chat input
const sendBtn = document.getElementById("send-btn");
const msgInput = document.getElementById("msg-input");

// =============================================================================
// BACKGROUND CANVAS
// =============================================================================
(function () {
  const c = document.getElementById("bg-canvas"), x = c.getContext("2d");
  function r() { c.width = window.innerWidth; c.height = window.innerHeight; d(); }
  function d() {
    x.clearRect(0, 0, c.width, c.height);
    const W = c.width, H = c.height, vx = W / 2, vy = H * 0.48;
    x.strokeStyle = "rgba(0,180,220,0.18)"; x.lineWidth = 0.6;
    for (let i = 0; i <= 20; i++) { const t = i / 20, y = H * 0.28 + t * H * 0.72; x.beginPath(); x.moveTo(vx - vx * t, y); x.lineTo(vx + (W - vx) * t, y); x.stroke(); }
    for (let i = 0; i <= 26; i++) { x.beginPath(); x.moveTo(vx, vy); x.lineTo((i / 26) * W, H); x.stroke(); }
  }
  r(); window.addEventListener("resize", r);
})();

// =============================================================================
// CLOCK
// =============================================================================
function tickClock() {
  const now = new Date(), o = { timeZone: userTimezone };
  clkTime.textContent = now.toLocaleTimeString("en-US", { ...o, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  clkDate.textContent = now.toLocaleDateString("en-US", { ...o, weekday: "short", month: "short", day: "2-digit", year: "numeric" });
}

async function detectRegion() {
  try { const r = await fetch("/region"); const d = await r.json(); userTimezone = d.timezone || "Intl.DateTimeFormat().resolvedOptions().timeZone"; } catch (_) { }
  tickClock(); setInterval(tickClock, 1000);
}

// =============================================================================
// CHAT RENDERING
// =============================================================================
function nowTS() { return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }); }
function md(t) { return t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>"); }

function addBubble(role, text) {
  const isAI = role === "ai";
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;
  row.innerHTML = `
    <div class="avatar">${isAI ? "AI" : "YOU"}</div>
    <div class="bdy">
      <span class="sender">${isAI ? "J.A.R.V.I.S" : "You"}</span>
      <div class="bubble">${md(text)}</div>
      <span class="ts">${nowTS()}</span>
    </div>`;
  chatArea.appendChild(row);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function showTyping() {
  removeTyping();
  const el = document.createElement("div"); el.id = "typing";
  el.innerHTML = `<div class="avatar" style="width:30px;height:30px;border-radius:50%;background:radial-gradient(circle,#002840,#001020);border:1px solid rgba(0,212,255,0.15);display:flex;align-items:center;justify-content:center;font-family:'Orbitron',monospace;font-size:9px;color:var(--cyan);margin-top:18px;">AI</div><div class="dots"><span></span><span></span><span></span></div>`;
  chatArea.appendChild(el); chatArea.scrollTop = chatArea.scrollHeight;
}
function removeTyping() { const el = document.getElementById("typing"); if (el) el.remove(); }

// =============================================================================
// SEND MESSAGE
// =============================================================================
async function send(textOverride) {
  if (isBusy) return;
  const text = (textOverride || msgInput.value).trim();
  if (!text) return;
  msgInput.value = ""; autoResize(); addBubble("user", text);
  isBusy = true; sendBtn.disabled = true; showTyping();
  JARVIS_Audio.chirp();

  try {
    interruptBtn.style.display = "flex";
    const res = await fetch("/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, timezone: userTimezone, image_context: lastCamContext })
    });
    const data = await res.json();
    removeTyping();
    const reply = data.response || "No response.";
    JARVIS_Audio.blip();
    addBubble("ai", reply);

    // Speak reply
    await speakAndWait(reply);

    // If continuous mode, restart listening after speaking
    if (continuousMode) {
      setTimeout(() => startListening(), 300);
    }
  } catch (e) {
    removeTyping();
    addBubble("ai", "⚠ Connection lost. Make sure `python app.py` is running.");
    if (continuousMode) setTimeout(() => startListening(), 1000);
  } finally {
    isBusy = false;
    sendBtn.disabled = false;
    interruptBtn.style.display = "none";
    if (!continuousMode) msgInput.focus();
  }
}

function interrupt() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  isBusy = false;
  removeTyping();
  addBubble("system", "Interruption protocol initiated. Awaiting further instructions.");
}

sendBtn.addEventListener("click", () => send());
msgInput.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
function autoResize() { msgInput.style.height = "auto"; msgInput.style.height = Math.min(msgInput.scrollHeight, 110) + "px"; }
msgInput.addEventListener("input", autoResize);

// =============================================================================
// VOICE INPUT — fresh instance each time, fixes Edge/Chrome
// =============================================================================
function buildRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  // In continuous mode, keep the recognizer alive across pauses
  r.continuous = continuousMode;
  r.interimResults = true;
  r.lang = "en-US";
  r.maxAlternatives = 1;

  r.onstart = () => { isListening = true; };
  r.onspeechstart = () => { if (voiceLabel) voiceLabel.textContent = "Hearing you…"; };

  r.onresult = (e) => {
    let final = "";
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) final += e.results[i][0].transcript;
      else interim += e.results[i][0].transcript;
    }
    // Show interim results in the voice overlay
    if (interim && voiceLabel) voiceLabel.textContent = interim + "…";
    if (final.trim()) {
      msgInput.value = final.trim(); autoResize();
      // In continuous mode, don't fully stop — just pause recognition while we process
      if (continuousMode) {
        try { recognition.stop(); } catch (_) { }
        isListening = false;
        if (voiceLabel) voiceLabel.textContent = "Processing…";
      } else {
        stopListening();
      }
      send(final.trim());
    }
  };

  r.onerror = (e) => {
    let msg = "Voice error.";
    if (e.error === "not-allowed") {
      msg = "Microphone blocked. Allow it in browser settings.";
      continuousMode = false;
      continuousBtn.classList.remove("active");
      stopListening();
      voiceOverlay.classList.add("hidden");
      addBubble("ai", msg);
      return;
    }
    if (e.error === "no-speech") {
      // In continuous mode, onend will auto-restart — do nothing here
      if (continuousMode) return;
      msg = "No speech detected. Try again.";
    }
    else if (e.error === "network") msg = "Network error with speech service.";
    else if (e.error === "aborted") return; // intentional stop
    else msg = `Voice error: ${e.error}`;
    if (!continuousMode) {
      stopListening();
      addBubble("ai", msg);
    }
  };

  r.onend = () => {
    // In continuous mode, auto-restart unless we're processing a message
    if (continuousMode) {
      if (!isBusy) {
        // Small delay then restart
        setTimeout(() => {
          if (continuousMode && !isBusy) {
            if (voiceLabel) voiceLabel.textContent = "Listening…";
            startListening();
          }
        }, 400);
      }
      // Keep the overlay visible
      return;
    }
    // Normal mode — just stop
    if (isListening) stopListening();
  };
  return r;
}

function startListening() {
  // Don't start if JARVIS is currently speaking
  if (window.speechSynthesis && window.speechSynthesis.speaking) {
    // Retry after a short delay in continuous mode
    if (continuousMode) setTimeout(() => startListening(), 500);
    return;
  }

  recognition = buildRecognition();
  if (!recognition) { addBubble("ai", "Speech recognition not supported. Try Chrome or Edge."); return; }
  try {
    recognition.start(); isListening = true;
    voiceBtn.classList.add("active");
    voiceOverlay.classList.remove("hidden");
    if (voiceLabel) voiceLabel.textContent = "Listening…";
    if (contIndicator) contIndicator.style.display = continuousMode ? "block" : "none";
  } catch (e) {
    // Already started — if in continuous mode, retry
    if (continuousMode) setTimeout(() => startListening(), 500);
  }
}

function stopListening() {
  isListening = false;
  try { if (recognition) recognition.stop(); } catch (_) { }
  voiceBtn.classList.remove("active");
  if (!continuousMode) voiceOverlay.classList.add("hidden");
}

voiceBtn.addEventListener("click", () => { isListening ? stopListening() : startListening(); });
stopVoiceBtn.addEventListener("click", () => {
  continuousMode = false;
  // continuousBtn.classList.remove("active"); // Button removed
  stopListening();
  voiceOverlay.classList.add("hidden");
});

// Continuous mode toggle - DISABLED (button removed)
// continuousBtn.addEventListener("click", () => {
//   continuousMode = !continuousMode;
//   continuousBtn.classList.toggle("active", continuousMode);
//   if (continuousMode) {
//     addBubble("ai", "🔄 **Continuous voice mode ON**. I'll listen automatically after each reply. Say anything!");
//     startListening();
//   } else {
//     stopListening();
//     voiceOverlay.classList.add("hidden");
//     addBubble("ai", "Continuous mode off.");
//   }
// });

// =============================================================================
// VOICE OUTPUT — returns Promise that resolves when speech ends
// =============================================================================
function speakAndWait(text) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis || !text) { resolve(); return; }
    window.speechSynthesis.cancel();
    const clean = text.replace(/\*\*/g, "").replace(/<[^>]+>/g, "").replace(/⚠/g, "Warning.").substring(0, 400);
    const u = new SpeechSynthesisUtterance(clean);
    u.rate = 1.0; u.pitch = 0.85; u.volume = 1.0;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    const go = () => {
      const v = window.speechSynthesis.getVoices();
      const eng = v.find(x => x.lang.startsWith("en-")) || v[0];
      if (eng) u.voice = eng;
      window.speechSynthesis.speak(u);
    };
    window.speechSynthesis.getVoices().length > 0 ? go() : (window.speechSynthesis.onvoiceschanged = go);
  });
}

// =============================================================================
// CAMERA — real-time webcam + frame analysis - DISABLED (button removed)
// =============================================================================
// camToggleBtn.addEventListener("click", async () => {
//   if (camPanel.classList.contains("hidden")) {
//     await startCamera();
//     camPanel.classList.remove("hidden");
//     camToggleBtn.classList.add("active");
//   } else {
//     stopCamera();
//   }
// });

camCloseBtn.addEventListener("click", stopCamera);

async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
    camVideo.srcObject = cameraStream;
    camOverlay.textContent = "Camera ready. Click Analyze Now or enable Auto.";
  } catch (e) {
    addBubble("ai", `Camera error: ${e.message}. Make sure you allow camera access.`);
  }
}

function stopCamera() {
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  camPanel.classList.add("hidden");
  camToggleBtn.classList.remove("active");
  if (autoInterval) { clearInterval(autoInterval); autoInterval = null; }
  autoAnalyze = false; camAutoBtn.classList.remove("active");
  lastCamContext = "";
}

camAnalyzeBtn.addEventListener("click", () => analyzeFrame("What do you see in this camera view? Be detailed."));

camAutoBtn.addEventListener("click", () => {
  autoAnalyze = !autoAnalyze;
  camAutoBtn.classList.toggle("active", autoAnalyze);
  if (autoAnalyze) {
    camOverlay.textContent = "Auto-analyzing every 5 seconds…";
    analyzeFrame("Briefly describe what you see.");
    autoInterval = setInterval(() => analyzeFrame("What changed? Briefly describe the current view."), 5000);
  } else {
    if (autoInterval) { clearInterval(autoInterval); autoInterval = null; }
    camOverlay.textContent = "Auto-analyze stopped.";
  }
});

async function analyzeFrame(question) {
  if (!cameraStream) return;
  try {
    const ctx2d = camCanvas.getContext("2d");
    camCanvas.width = camVideo.videoWidth || 320;
    camCanvas.height = camVideo.videoHeight || 240;
    ctx2d.drawImage(camVideo, 0, 0);
    const frameB64 = camCanvas.toDataURL("image/jpeg", 0.7);

    const r = await fetch("/analyze_frame", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frame: frameB64, question })
    });
    const d = await r.json();
    lastCamContext = d.description || "";
    camOverlay.textContent = lastCamContext;
  } catch (e) {
    camOverlay.textContent = `Error: ${e.message}`;
  }
}

// =============================================================================
// FILE UPLOAD - DISABLED (button removed)
// =============================================================================
// uploadToggle.addEventListener("click", () => {
//   uploadPanel.classList.toggle("hidden");
//   if (!uploadPanel.classList.contains("hidden")) kbPanel.classList.add("hidden");
// });
uploadClose.addEventListener("click", () => uploadPanel.classList.add("hidden"));

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("drag-over"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", e => {
  e.preventDefault(); dropZone.classList.remove("drag-over");
  if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files[0]) handleUpload(fileInput.files[0]); });

async function handleUpload(file) {
  uploadStatus.textContent = `Uploading ${file.name}…`;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("question", uploadQ.value || "Describe this in detail.");
  formData.append("save", saveFileCb.checked ? "true" : "false");

  try {
    const r = await fetch("/upload", { method: "POST", body: formData });
    const d = await r.json();
    uploadStatus.textContent = `Done: ${d.filename}`;
    uploadPanel.classList.add("hidden");
    addBubble("user", `[Uploaded: ${file.name}] ${uploadQ.value || "Describe this."}`);
    addBubble("ai", d.response || "File received.");
    speakAndWait(d.response || "");
  } catch (e) {
    uploadStatus.textContent = `Error: ${e.message}`;
  }
}

// =============================================================================
// KNOWLEDGE BASE PANEL
// =============================================================================
kbBtn.addEventListener("click", async () => {
  kbPanel.classList.toggle("hidden");
  if (!kbPanel.classList.contains("hidden")) {
    uploadPanel.classList.add("hidden");
    await loadKB();
  }
});
kbClose.addEventListener("click", () => kbPanel.classList.add("hidden"));

async function loadKB() {
  kbList.innerHTML = "<div class='kb-empty'>Loading…</div>";
  try {
    const r = await fetch("/knowledge");
    const d = await r.json();
    const kb = d.knowledge || {};
    if (!Object.keys(kb).length) { kbList.innerHTML = "<div class='kb-empty'>No knowledge learned yet.<br/>Say \"learn about [topic]\" to teach me.</div>"; return; }
    kbList.innerHTML = "";
    Object.entries(kb).forEach(([topic, data]) => {
      const el = document.createElement("div"); el.className = "kb-item";
      el.innerHTML = `
        <button class="kb-forget" onclick="forgetTopic('${topic.replace(/'/g, "\\'")}')">✕ Forget</button>
        <div class="kb-topic">${topic.toUpperCase()}</div>
        <div class="kb-content">${(data.content || "").substring(0, 200)}…</div>
        <div class="kb-date">Learned: ${data.learned_at || "unknown"}</div>`;
      kbList.appendChild(el);
    });
  } catch (e) { kbList.innerHTML = `<div class='kb-empty'>Error: ${e.message}</div>`; }
}

async function forgetTopic(topic) {
  await fetch("/knowledge/forget", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic }) });
  addBubble("ai", `Forgot knowledge about: ${topic}`);
  loadKB();
}
window.forgetTopic = forgetTopic;

// =============================================================================
// INIT
// =============================================================================
(async function () {
  await detectRegion();
  let greeting = "Good evening", timeStr = "";
  try {
    const r = await fetch(`/time?tz=${userTimezone}`);
    const d = await r.json();
    greeting = d.greeting || "Good evening";
    timeStr = d.time_str || "";
  } catch (_) { }

  addBubble("ai",
    `Welcome home, Sir. All systems are currently **functional**.\n\n` +
    `Current background protocols: **Optimized Pure Black**\n` +
    `Local Time: **${timeStr}**\n\n` +
    `I've consolidated the system controls into the **⚡ Menu** on your left for easier access across all your devices. ` +
    `You may now also **Interrupt** me at any time if you have urgent adjustments.\n\n` +
    `I'm standing by for your next command.`
  );

  // Power-on sound sequence
  setTimeout(() => {
    JARVIS_Audio.confirm();
    setTimeout(() => JARVIS_Audio.chirp(), 400);
  }, 100);

  setTimeout(() => speakAndWait(`${greeting} Sir. Systems online. How can I assist you?`), 600);
  msgInput.focus();
})();

// Menu Toggle
menuTrigger.addEventListener("click", () => {
  JARVIS_Audio.confirm();
  menuTrigger.classList.toggle("active");
  menuItems.classList.toggle("open");
});

// Lightning trigger also opens menu
if (lightningTrigger) {
  lightningTrigger.addEventListener("click", () => {
    JARVIS_Audio.confirm();
    menuTrigger.classList.toggle("active");
    menuItems.classList.toggle("open");
  });
}

// Close menu when clicking an item
document.querySelectorAll(".menu-item").forEach(item => {
  item.addEventListener("click", () => {
    JARVIS_Audio.ui();
    menuTrigger.classList.remove("active");
    menuItems.classList.remove("open");
  });
});

// Background Switcher
document.querySelectorAll(".bg-opt").forEach(btn => {
  btn.addEventListener("click", () => {
    JARVIS_Audio.blip();
    const bg = btn.getAttribute("data-bg");
    document.body.className = bg;
    localStorage.setItem("jarvis-bg", bg);
  });
});

// Load saved background
const savedBg = localStorage.getItem("jarvis-bg") || "bg-black";
document.body.className = savedBg;

// Interrupt binding
interruptBtn.addEventListener("click", (e) => {
  e.preventDefault();
  interrupt();
});
