"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Link2,
  CheckCircle2,
  XCircle,
  Loader2,
  Unplug,
  RefreshCcw,
  Eye,
  EyeOff,
  Github,
  Mail,
  Instagram,
  MessageCircle,
  Smartphone,
} from "lucide-react";

/* ======================================================================
   TYPES
   ====================================================================== */

type PlatformId = "github" | "vercel" | "gmail" | "instagram" | "telegram" | "whatsapp";

interface PlatformMeta {
  id: PlatformId;
  name: string;
  icon: React.ReactNode;
  color: string;
  glowColor: string;
  tokenLabel: string;
  helpUrl: string;
  helpText: string;
}

interface PlatformStatus {
  connected: boolean;
  username?: string;
  email?: string;
  avatar_url?: string;
  error?: string;
}

/* ======================================================================
   PLATFORM DEFINITIONS
   ====================================================================== */

const PLATFORMS: PlatformMeta[] = [
  {
    id: "github",
    name: "GitHub",
    icon: <Github size={20} />,
    color: "text-white",
    glowColor: "shadow-[0_0_20px_rgba(255,255,255,0.08)]",
    tokenLabel: "Personal Access Token",
    helpUrl: "https://github.com/settings/tokens",
    helpText: "Generate a classic PAT with repo + read:user scopes",
  },
  {
    id: "vercel",
    name: "Vercel",
    icon: <span className="text-lg font-bold">▲</span>,
    color: "text-white",
    glowColor: "shadow-[0_0_20px_rgba(255,255,255,0.08)]",
    tokenLabel: "API Token",
    helpUrl: "https://vercel.com/account/tokens",
    helpText: "Create an account-level API token from your Vercel dashboard",
  },
  {
    id: "gmail",
    name: "Gmail",
    icon: <Mail size={20} />,
    color: "text-rose-400",
    glowColor: "shadow-[0_0_20px_rgba(244,63,94,0.08)]",
    tokenLabel: "OAuth Token / App Password",
    helpUrl: "https://myaccount.google.com/apppasswords",
    helpText: "Use a Google App Password or OAuth refresh token",
  },
  {
    id: "instagram",
    name: "Instagram",
    icon: <Instagram size={20} />,
    color: "text-pink-400",
    glowColor: "shadow-[0_0_20px_rgba(236,72,153,0.08)]",
    tokenLabel: "Session Token",
    helpUrl: "#",
    helpText: "JARVIS uses browser automation — provide your session cookie or password",
  },
  {
    id: "telegram",
    name: "Telegram",
    icon: <MessageCircle size={20} />,
    color: "text-sky-400",
    glowColor: "shadow-[0_0_20px_rgba(56,189,248,0.08)]",
    tokenLabel: "Bot Token",
    helpUrl: "https://t.me/BotFather",
    helpText: "Create a bot via @BotFather and paste the token here",
  },
  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: <Smartphone size={20} />,
    color: "text-green-400",
    glowColor: "shadow-[0_0_20px_rgba(74,222,128,0.08)]",
    tokenLabel: "Session (Browser)",
    helpUrl: "#",
    helpText: "JARVIS connects via WhatsApp Web — scan QR code in the browser session",
  },
];

/* ======================================================================
   COMPONENT
   ====================================================================== */

export default function ConnectionsPage() {
  const [statuses, setStatuses] = useState<Record<string, PlatformStatus>>({});
  const [loading, setLoading] = useState(true);
  const [tokens, setTokens] = useState<Record<string, string>>({});
  const [showTokens, setShowTokens] = useState<Record<string, boolean>>({});
  const [connecting, setConnecting] = useState<Record<string, boolean>>({});
  const [disconnecting, setDisconnecting] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [successes, setSuccesses] = useState<Record<string, string>>({});

  /* ---- fetch status ---- */
  const fetchStatuses = useCallback(async () => {
    try {
      const res = await fetch("/api/connections/status", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setStatuses(data);
      }
    } catch {
      /* silently fail */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatuses();
    const iv = setInterval(() => void fetchStatuses(), 30_000);
    return () => clearInterval(iv);
  }, [fetchStatuses]);

  /* ---- connect ---- */
  const connect = async (platform: PlatformId) => {
    const token = tokens[platform]?.trim();
    if (!token) {
      setErrors((p) => ({ ...p, [platform]: "Token cannot be empty" }));
      return;
    }
    setConnecting((p) => ({ ...p, [platform]: true }));
    setErrors((p) => ({ ...p, [platform]: "" }));
    setSuccesses((p) => ({ ...p, [platform]: "" }));
    try {
      const res = await fetch("/api/connections/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform, token }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Connection failed" }));
        throw new Error(err.detail || "Connection failed");
      }
      const data = await res.json();
      setSuccesses((p) => ({
        ...p,
        [platform]: `Connected${data.username ? ` as ${data.username}` : ""}!`,
      }));
      setTokens((p) => ({ ...p, [platform]: "" }));
      await fetchStatuses();
    } catch (e: unknown) {
      setErrors((p) => ({ ...p, [platform]: e instanceof Error ? e.message : "Failed" }));
    } finally {
      setConnecting((p) => ({ ...p, [platform]: false }));
    }
  };

  /* ---- disconnect ---- */
  const disconnect = async (platform: PlatformId) => {
    setDisconnecting((p) => ({ ...p, [platform]: true }));
    setErrors((p) => ({ ...p, [platform]: "" }));
    setSuccesses((p) => ({ ...p, [platform]: "" }));
    try {
      await fetch(`/api/connections/disconnect/${platform}`, { method: "POST" });
      await fetchStatuses();
    } catch {
      /* silently fail */
    } finally {
      setDisconnecting((p) => ({ ...p, [platform]: false }));
    }
  };

  /* ---- helpers ---- */
  const connectedCount = Object.values(statuses).filter((s) => s.connected).length;

  return (
    <div className="space-y-6">
      {/* ---- HEADER ---- */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Connections</h1>
          <p className="text-sm text-slate-400 mt-1">
            Link JARVIS to your platforms for full autonomous control.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-400">
            <CheckCircle2 size={12} />
            {connectedCount} connected
          </span>
          <button
            onClick={() => {
              setLoading(true);
              void fetchStatuses();
            }}
            className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 transition-colors"
          >
            <RefreshCcw size={12} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* ---- PLATFORM CARDS ---- */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {PLATFORMS.map((plat) => {
          const st = statuses[plat.id];
          const isConnected = st?.connected === true;
          const isConnecting = connecting[plat.id];
          const isDisconnecting = disconnecting[plat.id];
          const error = errors[plat.id];
          const success = successes[plat.id];

          return (
            <div
              key={plat.id}
              className={`rounded-2xl border p-5 transition-all duration-300 ${
                isConnected
                  ? "border-emerald-500/20 bg-emerald-500/[0.03]"
                  : "border-slate-700/50 bg-slate-800/20"
              } ${plat.glowColor}`}
            >
              {/* Top row */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div
                    className={`flex items-center justify-center w-10 h-10 rounded-xl ${
                      isConnected
                        ? "bg-emerald-500/10 text-emerald-400"
                        : "bg-slate-700/50 text-slate-400"
                    }`}
                  >
                    {plat.icon}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">{plat.name}</div>
                    {isConnected && st?.username && (
                      <div className="text-xs text-emerald-400/80 mt-0.5">
                        @{st.username}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {isConnected ? (
                    <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-emerald-400">
                      <span className="inline-block h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
                      Connected
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      <span className="inline-block h-2 w-2 rounded-full bg-slate-600" />
                      Not connected
                    </span>
                  )}
                </div>
              </div>

              {/* Connection form or status */}
              {isConnected ? (
                <div className="flex items-center justify-between">
                  <p className="text-xs text-slate-500">
                    Token verified and stored securely in Vault.
                  </p>
                  <button
                    onClick={() => void disconnect(plat.id)}
                    disabled={isDisconnecting}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 transition-colors disabled:opacity-50"
                  >
                    {isDisconnecting ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Unplug size={12} />
                    )}
                    Disconnect
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="text-xs text-slate-500">{plat.helpText}</div>
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <input
                        type={showTokens[plat.id] ? "text" : "password"}
                        placeholder={plat.tokenLabel}
                        value={tokens[plat.id] || ""}
                        onChange={(e) =>
                          setTokens((p) => ({ ...p, [plat.id]: e.target.value }))
                        }
                        className="w-full rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 pr-8 text-sm text-slate-200 placeholder-slate-600 focus:border-jarvis-500 focus:outline-none focus:ring-1 focus:ring-jarvis-500/30 transition-colors"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setShowTokens((p) => ({ ...p, [plat.id]: !p[plat.id] }))
                        }
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                      >
                        {showTokens[plat.id] ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                    <button
                      onClick={() => void connect(plat.id)}
                      disabled={isConnecting || !tokens[plat.id]?.trim()}
                      className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold bg-jarvis-500 hover:bg-jarvis-600 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isConnecting ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Link2 size={14} />
                      )}
                      Connect
                    </button>
                  </div>
                  {plat.helpUrl && plat.helpUrl !== "#" && (
                    <a
                      href={plat.helpUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex text-[11px] text-jarvis-400 hover:text-jarvis-300 underline underline-offset-2 transition-colors"
                    >
                      How to get a token →
                    </a>
                  )}
                </div>
              )}

              {/* Error / Success messages */}
              {error && (
                <div className="mt-3 flex items-center gap-1.5 text-xs text-rose-400">
                  <XCircle size={12} />
                  {error}
                </div>
              )}
              {success && (
                <div className="mt-3 flex items-center gap-1.5 text-xs text-emerald-400">
                  <CheckCircle2 size={12} />
                  {success}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ---- INFO BOX ---- */}
      <div className="rounded-2xl border border-slate-700/30 bg-slate-800/10 p-5">
        <div className="text-sm font-semibold text-white mb-2">How connections work</div>
        <ul className="space-y-2 text-xs text-slate-500">
          <li className="flex items-start gap-2">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-jarvis-500/20 text-[10px] font-bold text-jarvis-300 mt-0.5">1</span>
            Tokens are verified against the platform API before being stored.
          </li>
          <li className="flex items-start gap-2">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-jarvis-500/20 text-[10px] font-bold text-jarvis-300 mt-0.5">2</span>
            Credentials are encrypted with AES-256-GCM in JARVIS Secure Vault.
          </li>
          <li className="flex items-start gap-2">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-jarvis-500/20 text-[10px] font-bold text-jarvis-300 mt-0.5">3</span>
            JARVIS uses these tokens to autonomously deploy, commit, email, and manage your accounts.
          </li>
        </ul>
      </div>
    </div>
  );
}
