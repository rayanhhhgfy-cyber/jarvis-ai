// =============================================================================
// script.js — JARVIS Frontend (Groq LLM powered)
// =============================================================================

"use strict";

let userTimezone = "UTC";
let isBusy = false;
let recognition = null;

const chatArea     = document.getElementById("chat-area");
const msgInput     = document.getElementById("msg-input");
const sendBtn      = document.getElementById("send-btn");
const voiceBtn     = document.getElementById("voice-btn");
const voiceOverlay = document.getElementById("voice-overlay");
const stopVoiceBtn = document.getElementById("stop-voice-btn");
const clkTime      = document.getElementById("clk-time");
const clkDate      = document.getElementById("clk-date");
const continuousTalkBtn = document.getElementById("continuous-talk-btn");
const uploadFileBtn = document.getElementById("upload-file-btn");
const cameraTalkBtn = document.getElementById("camera-talk-btn");

// =============================================================================
// BACKGROUND CANVAS
// =============================================================================
(function() {
  const canvas = document.getElementById("bg-canvas");
  const ctx = canvas.getContext("2d");

  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    draw();
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const W = canvas.width, H = canvas.height;
    const vx = W / 2, vy = H * 0.48;
    ctx.strokeStyle = "rgba(0, 180, 220, 0.18)";
    ctx.lineWidth = 0.6;
    for (let r = 0; r <= 20; r++) {
      const t = r / 20;
      const y = H * 0.28 + t * H * 0.72;
      ctx.beginPath();
      ctx.moveTo(vx - vx * t, y);
      ctx.lineTo(vx + (W - vx) * t, y);
      ctx.stroke();
    }
    for (let c = 0; c <= 26; c++) {
      ctx.beginPath();
      ctx.moveTo(vx, vy);
      ctx.lineTo((c / 26) * W, H);
      ctx.stroke();
    }
  }

  resize();
  window.addEventListener("resize", resize);
})();


// =============================================================================
// CLOCK
// =============================================================================
function tickClock() {
  const now = new Date();
  const o = { timeZone: userTimezone };
  clkTime.textContent = now.toLocaleTimeString("en-US", { ...o, hour:"2-digit", minute:"2-digit", second:"2-digit" });
  clkDate.textContent = now.toLocaleDateString("en-US",  { ...o, weekday:"short", month:"short", day:"2-digit", year:"numeric" });
}

async function detectRegion() {
  try {
    const r = await fetch("/region");
    const d = await r.json();
    userTimezone = d.timezone || "UTC";
  } catch(_) { userTimezone = "UTC"; }
  tickClock();
  setInterval(tickClock, 1000);
}


// =============================================================================
// CHAT RENDERING
// =============================================================================
function nowTS() {
  return new Date().toLocaleTimeString("en-US", { hour:"2-digit", minute:"2-digit" });
}

function renderMd(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function addBubble(role, text) {
  const isAI = role === "ai";
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;
  row.innerHTML = `
    <div class="avatar">${isAI ? "AI" : "YOU"}</div>
    <div class="bdy">
      <span class="sender">${isAI ? "J.A.R.V.I.S" : "You"}</span>
      <div class="bubble">${renderMd(text)}</div>
      <span class="ts">${nowTS()}</span>
    </div>`;
  chatArea.appendChild(row);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function showTyping() {
  removeTyping();
  const el = document.createElement("div");
  el.id = "typing";
  el.innerHTML = `
    <div class="avatar" style="width:30px;height:30px;border-radius:50%;background:radial-gradient(circle,#002840,#001020);border:1px solid rgba(0,212,255,0.15);display:flex;align-items:center;justify-content:center;font-family:'Orbitron',monospace;font-size:9px;color:var(--cyan);margin-top:18px;">AI</div>
    <div class="dots"><span></span><span></span><span></span></div>`;
  chatArea.appendChild(el);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById("typing");
  if (el) el.remove();
}


// =============================================================================
// SEND MESSAGE
// =============================================================================
async function send() {
  if (isBusy) return;
  const text = msgInput.value.trim();
  if (!text) return;

  msgInput.value = "";
  autoResize();
  addBubble("user", text);

  isBusy = true;
  sendBtn.disabled = true;
  showTyping();

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, timezone: userTimezone })
    });
    const data = await res.json();
    removeTyping();
    addBubble("ai", data.response || "No response received.");
    speak(data.response || "");
  } catch(err) {
    removeTyping();
    addBubble("ai", "⚠ Server connection lost. Make sure `python app.py` is running.");
  }

  isBusy = false;
  sendBtn.disabled = false;
  msgInput.focus();
}

sendBtn.addEventListener("click", send);
msgInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});


// =============================================================================
// AUTO-RESIZE TEXTAREA
// =============================================================================
function autoResize() {
  msgInput.style.height = "auto";
  msgInput.style.height = Math.min(msgInput.scrollHeight, 110) + "px";
}
msgInput.addEventListener("input", autoResize);


// =============================================================================
// VOICE INPUT
// =============================================================================
function initVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return false;
  recognition = new SR();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";
  recognition.onresult = e => {
    msgInput.value = e.results[0][0].transcript;
    autoResize();
    stopListening();
    send();
  };
  recognition.onerror = () => stopListening();
  recognition.onend   = () => stopListening();
  return true;
}

function startListening() {
  if (!recognition && !initVoice()) {
    addBubble("ai", "Voice input not supported in this browser. Try Chrome or Edge.");
    return;
  }
  recognition.start();
  voiceBtn.classList.add("active");
  voiceOverlay.classList.remove("hidden");
}

function stopListening() {
  try { if (recognition) recognition.stop(); } catch(_) {}
  voiceBtn.classList.remove("active");
  voiceOverlay.classList.add("hidden");
}

voiceBtn.addEventListener("click", () => {
  voiceBtn.classList.contains("active") ? stopListening() : startListening();
});
stopVoiceBtn.addEventListener("click", stopListening);


// =============================================================================
// VOICE OUTPUT
// =============================================================================
function speak(text) {
  if (!window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const clean = text.replace(/\*\*/g, "").replace(/<[^>]+>/g, "").replace(/⚠/g, "Warning.");
  const u = new SpeechSynthesisUtterance(clean);
  u.rate = 1.0; u.pitch = 0.85; u.volume = 1.0;
  const eng = window.speechSynthesis.getVoices().find(v => v.lang.startsWith("en"));
  if (eng) u.voice = eng;
  window.speechSynthesis.speak(u);
}
if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = () => {};


// =============================================================================
// INIT
// =============================================================================
(async function init() {
  await detectRegion();
  initVoice();

  let greeting = "Good day", timeStr = "";
  try {
    const r = await fetch(`/time?tz=${userTimezone}`);
    const d = await r.json();
    greeting = d.greeting || "Good day";
    timeStr  = d.time_str || "";
  } catch(_) {}

  addBubble("ai",
    `${greeting}, Rayan! I am **J.A.R.V.I.S**, now powered by **Llama 3.3 70B** via Groq.\n\n` +
    `Current time: **${timeStr}** (${userTimezone})\n\n` +
    `I can now **actually think** — ask me anything:\n` +
    `• Write and debug code\n` +
    `• Explain complex topics\n` +
    `• Solve problems step by step\n` +
    `• Search the web for current info\n` +
    `• Remember your name and preferences\n\n` +
  );

  msgInput.focus();
})();


// =============================================================================
// MENU FUNCTIONALITY
// =============================================================================
const menuBtn = document.querySelector('.menu-btn');
const menuOverlay = document.querySelector('.menu-overlay');
const closeMenuBtn = document.querySelector('.close-menu-btn');

if (menuBtn && menuOverlay && closeMenuBtn) {
  menuBtn.addEventListener('click', () => {
    menuOverlay.classList.add('active');
  });
  
  closeMenuBtn.addEventListener('click', () => {
    menuOverlay.classList.remove('active');
  });
  
  // Close menu when clicking outside
  menuOverlay.addEventListener('click', (e) => {
    if (e.target === menuOverlay) {
      menuOverlay.classList.remove('active');
    }
  });
}
