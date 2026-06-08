"use client";

import { useCallback, useEffect, useState } from "react";

type SubsystemId = "vision" | "sentinel" | "vault" | "captcha" | "voice" | "telegram" | "memory" | "research" | "social" | "improvement" | "focus_mode";

type Subsystem = {
  id: SubsystemId;
  icon: string;
  name: string;
  desc: string;
  api: string | null;
  status: "online" | "offline" | "checking";
};

const SUBSYSTEMS: Subsystem[] = [
  { id: "focus_mode", icon: "🎯", name: "Focus Mode", api: "/api/focus/status", status: "checking", desc: "Block distractions, queue messages, deep work" },
  { id: "vision", icon: "◈", name: "Multimodal Vision", api: "/api/vision/sampler-stats", status: "checking", desc: "Qwen-VL screen analysis, OCR, UI detection" },
  { id: "sentinel", icon: "⚡", name: "Proactive Sentinel", api: "/api/sentinel/health", status: "checking", desc: "Self-healing, auto-fix, service monitoring" },
  { id: "vault", icon: "🔒", name: "Secure Vault", api: "/api/vault/status", status: "checking", desc: "AES-256-GCM encrypted credential storage" },
  { id: "captcha", icon: "⊡", name: "CAPTCHA Autonomy", api: null, status: "checking", desc: "Vision-based CAPTCHA solving via Qwen-VL" },
  { id: "voice", icon: "♪", name: "Voice Protocol", api: null, status: "checking", desc: "Local pyttsx3 speech, wake word, STT" },
  { id: "telegram", icon: "✉", name: "Cross-Device Bridge", api: "/api/telegram/status", status: "checking", desc: "Telegram remote commands & screen sharing" },
  { id: "memory", icon: "▦", name: "Workspace RAG 2.0", api: "/api/memory/workspace-stats", status: "checking", desc: "Continuous codebase indexing into ChromaDB" },
  { id: "research", icon: "◎", name: "Night Shift Researcher", api: "/api/research/briefing", status: "checking", desc: "Scheduled deep-dives and daily briefings" },
  { id: "social", icon: "◉", name: "Social Sentinel", api: "/api/social/pending", status: "checking", desc: "LinkedIn/X monitoring & response drafting" },
  { id: "improvement", icon: "⟳", name: "Self-Improvement Loop", api: "/api/improvement/lessons", status: "checking", desc: "Failure analysis, instruction evolution" },
];

async function checkStatus(sys: Subsystem): Promise<"online" | "offline"> {
  if (!sys.api) return "online";
  try {
    const res = await fetch(sys.api, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    return res.ok ? "online" : "offline";
  } catch {
    return "offline";
  }
}

export function SubsystemGrid() {
  const [expanded, setExpanded] = useState(true);
  const [statuses, setStatuses] = useState<Record<string, "online" | "offline" | "checking">>({});

  const refreshAll = useCallback(async () => {
    const results: Record<string, "online" | "offline" | "checking"> = {};
    for (const sys of SUBSYSTEMS) {
      results[sys.id] = await checkStatus(sys);
    }
    setStatuses(results);
  }, []);

  useEffect(() => {
    void refreshAll();
    const interval = setInterval(() => void refreshAll(), 15000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  const onlineCount = Object.values(statuses).filter((s) => s === "online").length;

  return (
    <div className="glass rounded-2xl p-4">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2"
      >
        <div className="flex items-center gap-3">
          <div className="text-lg font-semibold text-white">Subsystem Rooms</div>
          <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400">
            {onlineCount}/{SUBSYSTEMS.length} online
          </span>
        </div>
        <svg
          className={`h-4 w-4 text-slate-500 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {SUBSYSTEMS.map((sys) => {
            const st = statuses[sys.id] || "checking";
            const isOnline = st === "online";
            const isChecking = st === "checking";
            return (
              <div
                key={sys.id}
                className={`rounded-xl border p-4 transition-all ${
                  isOnline
                    ? "border-emerald-500/20 bg-emerald-500/[0.03]"
                    : "border-slate-700/50 bg-slate-800/20 hover:border-slate-600"
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xl">{sys.icon}</span>
                  <span
                    className={`inline-flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider ${
                      isOnline ? "text-emerald-400" : isChecking ? "text-slate-500" : "text-rose-400"
                    }`}
                  >
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        isOnline
                          ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]"
                          : isChecking
                            ? "bg-slate-600"
                            : "bg-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.5)]"
                      }`}
                    />
                    {isOnline ? "Online" : isChecking ? "..." : "Offline"}
                  </span>
                </div>
                <div className="text-sm font-medium text-white">{sys.name}</div>
                <div className="mt-1 text-[11px] text-slate-500 leading-snug">{sys.desc}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
