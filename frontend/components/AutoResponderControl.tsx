"use client";

import { useEffect, useState, useCallback } from "react";
import { Bot, Play, Square, Clock, AlertCircle, MessageCircle } from "lucide-react";

type AutoResponderStatus = {
  active: boolean;
  timeout_minutes: number;
  max_replies: number;
  tracked_threads: number;
};

export function AutoResponderControl() {
  const [status, setStatus] = useState<AutoResponderStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [timeoutValue, setTimeoutValue] = useState(5);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/auto-responder/status", { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as AutoResponderStatus;
        setStatus(data);
        setTimeoutValue(data.timeout_minutes);
      }
    } catch (err) {
      console.error("Failed to fetch auto-responder status", err);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
    const timer = setInterval(() => void fetchStatus(), 15000);
    return () => clearInterval(timer);
  }, [fetchStatus]);

  const handleToggle = async () => {
    setLoading(true);
    setError(null);
    try {
      // Save timeout first if changed
      if (timeoutValue !== (status?.timeout_minutes ?? 5)) {
        await fetch("/api/auto-responder/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timeout_minutes: timeoutValue }),
        });
      }
      const res = await fetch("/api/auto-responder/toggle", { method: "POST" });
      if (!res.ok) throw new Error("Failed to toggle AutoResponder");
      const data = (await res.json()) as AutoResponderStatus;
      setStatus(data);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const isActive = status?.active ?? false;

  return (
    <div className="glass rounded-2xl p-4 md:p-6 transition-all duration-300 border border-slate-700/50 hover:border-slate-600/50">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className={`p-3 rounded-xl ${isActive ? "bg-emerald-500/10 text-emerald-400" : "bg-jarvis-500/10 text-jarvis-400"}`}>
            {isActive ? <Bot className="h-6 w-6 animate-pulse" /> : <Bot className="h-6 w-6" />}
          </div>
          <div>
            <div className="text-sm text-slate-400 font-semibold tracking-wider uppercase">Smart DM Assistant</div>
            <div className="text-white text-xl font-bold mt-0.5 flex items-center gap-2">
              AutoResponder
              {isActive && (
                <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-400 animate-pulse">
                  Active
                </span>
              )}
            </div>
            <p className="text-sm text-slate-400 mt-1">
              {isActive
                ? `Watching ${status?.tracked_threads ?? 0} conversations — auto-responding after ${status?.timeout_minutes ?? timeoutValue} min of no reply`
                : "Automatically respond to DMs when you take too long to reply. Jarvis will engage naturally in the conversation until you come back."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end md:self-auto">
          {isActive ? (
            <button
              type="button"
              onClick={handleToggle}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-rose-500 hover:bg-rose-600 disabled:opacity-50 text-white font-semibold shadow-lg shadow-rose-500/20 transition-all duration-200"
            >
              <Square size={16} />
              {loading ? "Stopping…" : "Stop"}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleToggle}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-jarvis-500 hover:bg-jarvis-600 disabled:opacity-50 text-white font-semibold shadow-lg shadow-jarvis-500/20 transition-all duration-200"
            >
              <Play size={16} />
              {loading ? "Starting…" : "Start"}
            </button>
          )}
        </div>
      </div>

      {/* Settings when inactive */}
      {!isActive && (
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-slate-700/50 pt-5">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Response Timeout (minutes)
            </label>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={1}
                max={30}
                value={timeoutValue}
                onChange={(e) => setTimeoutValue(Number(e.target.value))}
                className="flex-1 accent-jarvis-500"
              />
              <span className="text-white font-mono font-bold text-sm min-w-[3rem] text-right">
                {timeoutValue}m
              </span>
            </div>
            <p className="text-[11px] text-slate-500">
              If you haven&apos;t replied within {timeoutValue} minute{timeoutValue > 1 ? "s" : ""}, Jarvis sends a heads-up and engages in the conversation.
            </p>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</label>
            <div className="flex items-center gap-2 text-sm">
              <span className={`h-2.5 w-2.5 rounded-full ${isActive ? "bg-emerald-500" : "bg-slate-600"}`} />
              <span className="text-slate-400">{isActive ? "Running" : "Idle"}</span>
            </div>
          </div>
        </div>
      )}

      {/* Active status */}
      {isActive && status && (
        <div className="mt-5 border-t border-slate-700/50 pt-4 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm">
          <div className="flex items-center gap-2 text-emerald-400">
            <Clock size={16} />
            <span className="font-mono font-bold tracking-wide">
              {status.timeout_minutes} min
            </span>
            <span className="text-slate-500">timeout</span>
          </div>
          <div className="flex items-center gap-2 text-slate-400 bg-slate-900/30 px-3.5 py-1.5 rounded-lg border border-slate-700/30">
            <MessageCircle size={14} />
            <span>Tracking: <strong className="text-white font-semibold">{status.tracked_threads}</strong> threads</span>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-center gap-2 text-rose-400 bg-rose-500/10 px-4 py-2.5 rounded-xl border border-rose-500/20 text-sm">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
