"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Play, Square, Coffee, Clock, Shield, AlertCircle, MessageSquare } from "lucide-react";

type FocusStatus = {
  active: boolean;
  focus_note: string;
  expires_at: string | null;
  time_remaining_seconds: number | null;
  auto_reply_enabled: boolean;
  queued_count: number;
};

type QueuedMessage = {
  sender: string;
  platform: string;
  text: string;
  received_at: string;
};

export function FocusModeControl() {
  const [status, setStatus] = useState<FocusStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState("Deep work session");
  const [duration, setDuration] = useState<number>(30); // 30 minutes default
  const [error, setError] = useState<string | null>(null);
  
  // Results from deactivation
  const [summary, setSummary] = useState<string | null>(null);
  const [missedMessages, setMissedMessages] = useState<QueuedMessage[]>([]);
  const [showDeactivationResults, setShowDeactivationResults] = useState(false);

  // Timer state for active countdown
  const [countdown, setCountdown] = useState<number | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/focus/status", { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as FocusStatus;
        setStatus(data);
        if (data.active && data.time_remaining_seconds !== null) {
          setCountdown(Math.round(data.time_remaining_seconds));
        } else {
          setCountdown(null);
        }
      }
    } catch (err) {
      console.error("Failed to fetch focus status", err);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
    const timer = setInterval(() => {
      void fetchStatus();
    }, 15000); // refresh status periodically
    return () => clearInterval(timer);
  }, [fetchStatus]);

  // Countdown timer effect
  useEffect(() => {
    if (countdown === null || countdown <= 0) return;
    const interval = setInterval(() => {
      setCountdown((prev) => (prev !== null ? Math.max(0, prev - 1) : null));
    }, 1000);
    return () => clearInterval(interval);
  }, [countdown]);

  const handleActivate = async () => {
    setLoading(true);
    setError(null);
    setShowDeactivationResults(false);
    try {
      const res = await fetch("/api/focus/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note,
          duration_minutes: duration > 0 ? duration : null,
        }),
      });
      if (!res.ok) throw new Error("Failed to activate Focus Mode");
      const data = (await res.json()) as FocusStatus;
      setStatus(data);
      if (data.active && data.time_remaining_seconds !== null) {
        setCountdown(Math.round(data.time_remaining_seconds));
      }
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleDeactivate = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/focus/deactivate", { method: "POST" });
      if (!res.ok) throw new Error("Failed to deactivate Focus Mode");
      const data = await res.json();
      setStatus(data.status);
      setCountdown(null);
      setSummary(data.summary || "No new messages missed during your focus session.");
      setMissedMessages(data.queued_messages || []);
      setShowDeactivationResults(true);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const formatTime = (totalSeconds: number) => {
    const hrs = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    const secs = totalSeconds % 60;
    if (hrs > 0) {
      return `${hrs}h ${mins}m ${secs}s`;
    }
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const safeStatus = status || { active: false, focus_note: "", expires_at: null, time_remaining_seconds: null, auto_reply_enabled: true, queued_count: 0 };

  return (
    <div className="glass rounded-2xl p-4 md:p-6 transition-all duration-300 border border-slate-700/50 hover:border-slate-600/50">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className={`p-3 rounded-xl ${safeStatus.active ? "bg-amber-500/10 text-amber-400" : "bg-jarvis-500/10 text-jarvis-400"}`}>
            {safeStatus.active ? <Coffee className="h-6 w-6 animate-pulse" /> : <Shield className="h-6 w-6" />}
          </div>
          <div>
            <div className="text-sm text-slate-400 font-semibold tracking-wider uppercase">Productivity protocol</div>
            <div className="text-white text-xl font-bold mt-0.5 flex items-center gap-2">
              Focus Mode
              {safeStatus.active && (
                <span className="inline-flex items-center rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-400 animate-pulse">
                  Active
                </span>
              )}
            </div>
            <p className="text-sm text-slate-400 mt-1">
              {safeStatus.active
                ? `Blocking distractions & auto-replying: "${safeStatus.focus_note}"`
                : "Queue incoming messages & auto-reply polite status updates while you concentrate."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end md:self-auto">
          {safeStatus.active ? (
            <button
              type="button"
              onClick={handleDeactivate}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-rose-500 hover:bg-rose-600 disabled:opacity-50 text-white font-semibold shadow-lg shadow-rose-500/20 transition-all duration-200"
            >
              <Square size={16} />
              {loading ? "Deactivating…" : "End Session"}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => handleActivate()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-jarvis-500 hover:bg-jarvis-600 disabled:opacity-50 text-white font-semibold shadow-lg shadow-jarvis-500/20 transition-all duration-200"
            >
              <Play size={16} />
              {loading ? "Activating…" : "Start Focus"}
            </button>
          )}
        </div>
      </div>

      {/* Configuration options when focus mode is inactive */}
      {!safeStatus.active && (
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-slate-700/50 pt-5">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Focus Activity Note</label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Coding a feature, Studying, Meeting"
              className="w-full rounded-xl bg-slate-900/50 border border-slate-700/60 px-4 py-2.5 text-sm text-white focus:outline-none focus:border-jarvis-500/80 transition-colors"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Duration (Minutes)</label>
            <div className="flex items-center gap-2">
              <select
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="flex-1 rounded-xl bg-slate-900/50 border border-slate-700/60 px-4 py-2.5 text-sm text-white focus:outline-none focus:border-jarvis-500/80 transition-colors"
              >
                <option value={15}>15 Minutes</option>
                <option value={25}>25 Minutes (Pomodoro)</option>
                <option value={30}>30 Minutes</option>
                <option value={45}>45 Minutes</option>
                <option value={60}>1 Hour</option>
                <option value={90}>1.5 Hours</option>
                <option value={120}>2 Hours</option>
                <option value={0}>Until turned off</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Active countdown display */}
      {safeStatus.active && (
        <div className="mt-5 border-t border-slate-700/50 pt-4 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm">
          <div className="flex items-center gap-2 text-amber-400">
            <Clock size={16} />
            <span className="font-mono font-bold tracking-wide">
              {countdown !== null
                ? formatTime(countdown)
                : "Indefinite session"}
            </span>
            <span className="text-slate-500">remaining</span>
          </div>

          <div className="flex items-center gap-2 text-slate-400 bg-slate-900/30 px-3.5 py-1.5 rounded-lg border border-slate-700/30">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
            <span>Queued messages: <strong className="text-white font-semibold">{safeStatus.queued_count}</strong></span>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-center gap-2 text-rose-400 bg-rose-500/10 px-4 py-2.5 rounded-xl border border-rose-500/20 text-sm">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Show summary of missed messages upon deactivation */}
      {showDeactivationResults && (
        <div className="mt-6 border-t border-slate-700/50 pt-5 space-y-4">
          <div className="bg-emerald-500/[0.03] border border-emerald-500/20 rounded-xl p-4">
            <h4 className="text-sm font-semibold text-emerald-400 flex items-center gap-1.5 mb-2">
              <Shield size={16} />
              Session Wrap-up & Briefing
            </h4>
            <p className="text-sm text-slate-300 leading-relaxed font-medium">
              {summary}
            </p>
          </div>

          {missedMessages.length > 0 && (
            <div className="space-y-2">
              <h5 className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
                <MessageSquare size={14} />
                Queued Messages ({missedMessages.length})
              </h5>
              <div className="max-h-60 overflow-y-auto space-y-2 pr-1 custom-scrollbar">
                {missedMessages.map((msg, index) => (
                  <div key={index} className="bg-slate-900/40 border border-slate-800 rounded-xl p-3.5 flex flex-col gap-1 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-white">{msg.sender}</span>
                      <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded uppercase font-bold tracking-wider">{msg.platform}</span>
                    </div>
                    <p className="text-slate-300 italic">&ldquo;{msg.text}&rdquo;</p>
                    <span className="text-[10px] text-slate-500 mt-1 self-end">
                      {new Date(msg.received_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
