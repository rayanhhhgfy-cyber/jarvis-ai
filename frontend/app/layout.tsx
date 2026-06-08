"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { MessageSquare, Settings, Image, Layers, Ear, EarOff, Loader2, Hammer, Film, Link2, Target } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import "./globals.css";

function useWakeWordListener() {
  const wsRef = useRef<WebSocket | null>(null);
  const [wakeEvent, setWakeEvent] = useState<{ time: number; text: string } | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(`${proto}//${host}/ws/ui`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "wake_word_detected") {
          setWakeEvent({ time: Date.now(), text: msg.payload?.text || "" });
          window.focus();
          if (Notification.permission === "granted") {
            new Notification("JARVIS", { body: "Listening... How can I help you, Sir?" });
          }
          setTimeout(() => setWakeEvent(null), 5000);
        }
      } catch {}
    };
    ws.onclose = () => { wsRef.current = null; };
    return () => { ws.close(); };
  }, []);

  return wakeEvent;
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [listening, setListening] = useState(false);
  const [checking, setChecking] = useState(true);
  const [focusActive, setFocusActive] = useState(false);
  const [focusChecking, setFocusChecking] = useState(true);
  const wakeEvent = useWakeWordListener();

  const checkFocusStatus = useCallback(async () => {
    try {
      const r = await fetch("/api/focus/status", { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setFocusActive(d.active || false);
      }
    } catch {}
    finally {
      setFocusChecking(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/listening/status", { cache: "no-store" })
      .then(r => r.json())
      .then(d => setListening(d.listening || false))
      .catch(() => {})
      .finally(() => setChecking(false));

    checkFocusStatus();
    const interval = setInterval(checkFocusStatus, 5000);
    return () => clearInterval(interval);
  }, [checkFocusStatus]);

  const toggleListening = async () => {
    try {
      if (listening) {
        await fetch("/api/listening/stop", { method: "POST" });
        setListening(false);
      } else {
        if (Notification.permission === "default") Notification.requestPermission();
        await fetch("/api/listening/start", { method: "POST" });
        setListening(true);
      }
    } catch {}
  };

  const toggleFocus = async () => {
    try {
      if (focusActive) {
        await fetch("/api/focus/deactivate", { method: "POST" });
        setFocusActive(false);
      } else {
        await fetch("/api/focus/activate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: "Deep Work", duration_minutes: 60 }),
        });
        setFocusActive(true);
      }
    } catch {}
  };

  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        {wakeEvent && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm pointer-events-none">
            <div className="rounded-2xl border border-emerald-500/30 bg-slate-900/90 px-8 py-6 text-center shadow-[0_0_60px_rgba(16,185,129,0.15)]">
              <div className="text-4xl mb-3 animate-pulse">🎧</div>
              <div className="text-lg font-semibold text-emerald-300">JARVIS Listening...</div>
              <div className="text-xs text-slate-500 mt-1">How can I help you, Sir?</div>
            </div>
          </div>
        )}
        <nav className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="text-xl font-bold text-jarvis-400">JARVIS</span>
            <span className="text-xs text-slate-500">OMEGA</span>
            <button
              onClick={toggleListening}
              disabled={checking}
              className={`ml-3 flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition-colors ${
                listening
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30"
                  : "bg-slate-800/50 text-slate-500 border border-slate-700/50 hover:text-slate-300"
              }`}
              title={listening ? "Always listening — click to stop" : "Click to enable always-listening"}
            >
              {checking ? (
                <Loader2 size={12} className="animate-spin" />
              ) : listening ? (
                <>
                  <Ear size={12} className="animate-pulse" />
                  Listening
                </>
              ) : (
                <>
                  <EarOff size={12} />
                  Listening
                </>
              )}
            </button>
            <button
              onClick={toggleFocus}
              disabled={focusChecking}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition-colors ${
                focusActive
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30"
                  : "bg-slate-800/50 text-slate-500 border border-slate-700/50 hover:text-slate-300"
              }`}
              title={focusActive ? "Focus Mode active — click to turn off" : "Click to activate Focus Mode"}
            >
              {focusChecking ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <>
                  <Target size={12} className={focusActive ? "animate-pulse" : ""} />
                  Focus
                </>
              )}
            </button>
          </div>
          <div className="flex items-center gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
            <Link
              href="/"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <MessageSquare size={16} />
              Chat
            </Link>
            <Link
              href="/rooms"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/rooms"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Layers size={16} />
              Rooms
            </Link>
            <Link
              href="/build"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/build"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Hammer size={16} />
              Build
            </Link>
            <Link
              href="/clips"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/clips"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Film size={16} />
              Clips
            </Link>
            <Link
              href="/connections"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/connections"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Link2 size={16} />
              Connections
            </Link>
            <Link
              href="/media"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/media"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Image size={16} />
              Media
            </Link>
            <Link
              href="/settings"
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                pathname === "/settings"
                  ? "bg-jarvis-500/20 text-jarvis-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Settings size={16} />
              Settings
            </Link>
          </div>
        </nav>
        <main className="mx-auto max-w-6xl p-4 lg:p-6">{children}</main>
        <div className="fixed bottom-3 left-3 rounded-md bg-slate-900/80 px-2 py-1 text-[10px] text-slate-600 border border-slate-800/50 select-none">
          v1.0212
        </div>
      </body>
    </html>
  );
}
