"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { QrCode, Smartphone, CheckCircle, Clock } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { ChatPanel, type ChatMessage } from "./ChatPanel";
import { DownloadHub } from "./DownloadHub";
import { LoadingShimmer } from "./LoadingShimmer";
import { SidebarDeviceStatus, DeviceTypePill } from "./SidebarDeviceStatus";
import { AgentStatusGrid } from "./AgentStatusGrid";
import { SubsystemGrid } from "./SubsystemGrid";
import { FocusModeControl } from "./FocusModeControl";
import {
  ensureDesktopTrusted,
  fetchConnectedDevices,
  generatePairingQr,
} from "../lib/api";
import { getWebSocketBaseUrl } from "../lib/config";
import { subscribeJarvisWs } from "../lib/jarvisWs";

type PairPayload = {
  user_id: string;
  desktop_device_id: string;
  pairing_secret: string;
  base_url: string;
  expires_at: number;
};

function useDesktopDeviceId(): string {
  const [id, setId] = useState("");
  useEffect(() => {
    const key = "jarvis.desktop.device_id";
    const existing = window.localStorage.getItem(key);
    if (existing) {
      setId(existing);
      return;
    }
    const created = `desktop-${Math.random().toString(16).slice(2)}-${Date.now()}`;
    window.localStorage.setItem(key, created);
    setId(created);
  }, []);
  return id;
}

export function LocalDashboard() {
  const desktopDeviceId = useDesktopDeviceId();
  const [ready, setReady] = useState(false);
  const [wsStatus, setWsStatus] = useState<"disconnected" | "connecting" | "connected">(
    "disconnected",
  );
  const [wsError, setWsError] = useState<string | null>(null);
  const [desktopOnline, setDesktopOnline] = useState(false);
  const [mobileOnline, setMobileOnline] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(() => {
    try {
      const stored = window.localStorage.getItem("jarvis.chat.messages");
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) return parsed as ChatMessage[];
      }
    } catch {}
    return [];
  });
  const chatInitialized = useRef(false);
  useEffect(() => {
    if (!chatInitialized.current) { chatInitialized.current = true; return; }
    try {
      window.localStorage.setItem("jarvis.chat.messages", JSON.stringify(chatMessages));
    } catch {}
  }, [chatMessages]);
  const [pairPayload, setPairPayload] = useState<PairPayload | null>(null);
  const [pairingLoading, setPairingLoading] = useState(false);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const [phonePaired, setPhonePaired] = useState(false);
  const [qrExpiry, setQrExpiry] = useState<number | null>(null);

  const refreshDevices = useCallback(async () => {
    const devices = await fetchConnectedDevices(null);
    const mobileFound = devices.some(
      (d) =>
        (d.device_type === "mobile" || d.device_type === "tablet") && d.online !== false,
    );
    setMobileOnline(mobileFound);
    if (mobileFound) setPhonePaired(true);
    setDesktopOnline(
      devices.some(
        (d) =>
          (d.device_type === "desktop" || d.device_type === "laptop") && d.online !== false,
      ),
    );
  }, []);

  useEffect(() => {
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    void refreshDevices();
    const poll = window.setInterval(() => void refreshDevices(), 10000);
    return () => window.clearInterval(poll);
  }, [ready, refreshDevices]);

  useEffect(() => {
    if (!ready) return;
    return subscribeJarvisWs((st, err) => {
      setWsStatus(st);
      setWsError(err);
      if (st === "connected") void refreshDevices();
    });
  }, [ready, refreshDevices]);

  const generatePairing = async () => {
    setPairingLoading(true);
    setPairingError(null);
    setQrExpiry(null);
    try {
      await ensureDesktopTrusted(null, desktopDeviceId, "Jarvis Web Desktop");
      const data = await generatePairingQr(null, desktopDeviceId);
      setPairPayload(data);
      const expiresIn = Math.max(0, Math.round((data.expires_at * 1000 - Date.now()) / 1000));
      setQrExpiry(expiresIn);
    } catch (e: unknown) {
      setPairingError(e instanceof Error ? e.message : "Failed to generate pairing");
      setPairPayload(null);
    } finally {
      setPairingLoading(false);
    }
  };

  const qrValue = useMemo(() => {
    if (!pairPayload) return "";
    return JSON.stringify({
      user_id: pairPayload.user_id,
      desktop_device_id: pairPayload.desktop_device_id,
      pairing_secret: pairPayload.pairing_secret,
      base_url: pairPayload.base_url,
      expires_at: pairPayload.expires_at,
    });
  }, [pairPayload]);

  // Countdown timer for QR expiry
  useEffect(() => {
    if (qrExpiry === null || qrExpiry <= 0) return;
    const timer = setInterval(() => {
      setQrExpiry((prev) => (prev !== null ? Math.max(0, prev - 1) : null));
    }, 1000);
    return () => clearInterval(timer);
  }, [qrExpiry]);

  if (!ready) {
    return (
      <div className="flex items-center justify-center py-24">
        <LoadingShimmer />
      </div>
    );
  }

  return (
    <div className="flex flex-col lg:flex-row gap-6">
          <aside className="w-full lg:w-72 space-y-4">
            <div className="glass rounded-2xl p-4 space-y-3">
              <div className="text-lg font-semibold text-white">Devices</div>
              <SidebarDeviceStatus
                title="Desktop Client"
                status={desktopOnline ? "online" : "offline"}
                detail="WebSocket companion"
                type={DeviceTypePill.DESKTOP}
              />
              <SidebarDeviceStatus
                title="Android Device"
                status={mobileOnline ? "online" : "offline"}
                detail="Accessibility + automation"
                type={DeviceTypePill.MOBILE}
              />
              <SidebarDeviceStatus
                title="Server WS"
                status={wsStatus === "connected" ? "online" : "offline"}
                detail={
                  wsStatus === "connected"
                    ? getWebSocketBaseUrl().replace(/^ws/, "http")
                    : wsError || wsStatus
                }
                type={DeviceTypePill.DESKTOP}
              />
            </div>
            <DownloadHub />
          </aside>

          <main className="flex-1 space-y-4">
            <div className="glass rounded-2xl p-4 md:p-6">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div>
                  <div className="text-jarvis-300 text-sm font-semibold">Cross-device pairing</div>
                  <div className="text-white text-xl font-bold mt-1">Pair your phone</div>
                  <p className="text-sm text-slate-400 mt-1">
                    {phonePaired
                      ? "Your Android device is connected."
                      : "Scan the QR code with the JARVIS Android app."}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {phonePaired && (
                    <span className="flex items-center gap-1 text-sm text-emerald-400">
                      <CheckCircle size={16} />
                      Paired
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => void generatePairing()}
                    disabled={pairingLoading || !desktopDeviceId}
                    className="inline-flex items-center gap-2 rounded-xl px-4 py-2 bg-jarvis-500 hover:bg-jarvis-600 text-white font-semibold disabled:opacity-60"
                  >
                    <QrCode size={16} />
                    {pairingLoading ? "Generating…" : phonePaired ? "Re-pair" : "Pair Phone"}
                  </button>
                </div>
              </div>
              {pairingError ? (
                <p className="text-sm text-rose-400 mt-3">{pairingError}</p>
              ) : null}
              {pairPayload && qrValue ? (
                <div className="mt-6 flex flex-col items-center gap-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 items-center w-full max-w-md">
                    <div className="flex justify-center">
                      <div className="bg-white rounded-xl p-4 shadow-[0_0_32px_rgba(14,165,233,0.12)]">
                        <QRCodeSVG value={qrValue} size={180} level="M" includeMargin />
                      </div>
                    </div>
                    <div className="space-y-3 text-sm">
                      <div className="flex items-start gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-jarvis-500/20 text-xs font-bold text-jarvis-300">1</span>
                        <span className="text-slate-300">Install JARVIS Android app</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-jarvis-500/20 text-xs font-bold text-jarvis-300">2</span>
                        <span className="text-slate-300">Open app and tap <strong>Pair Device</strong></span>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-jarvis-500/20 text-xs font-bold text-jarvis-300">3</span>
                        <span className="text-slate-300">Scan this QR code to connect</span>
                      </div>
                      {qrExpiry !== null && (
                        <div className="flex items-center gap-2 pt-2 text-slate-400">
                          <Clock size={14} />
                          <span className="text-xs">
                            {qrExpiry > 0
                              ? `Expires in ${Math.floor(qrExpiry / 60)}:${String(qrExpiry % 60).padStart(2, "0")}`
                              : "Expired — generate a new code"}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : !phonePaired ? (
                <div className="mt-4 flex items-center gap-2 rounded-xl border border-dashed border-slate-700 px-4 py-3 text-sm text-slate-500">
                  <Smartphone size={16} />
                  Tap &ldquo;Pair Phone&rdquo; to generate a QR code for the JARVIS Android app.
                </div>
              ) : null}
            </div>

            <AgentStatusGrid />

            <SubsystemGrid />

            <FocusModeControl />

            <div className="glass rounded-2xl p-4 md:p-6">
              <ChatPanel
                messages={chatMessages}
                onMessagesChange={setChatMessages}
                desktopDeviceId={desktopDeviceId}
              />
            </div>
          </main>
    </div>
  );
}
