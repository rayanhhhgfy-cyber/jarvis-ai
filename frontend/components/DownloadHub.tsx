"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Monitor, Smartphone, AlertCircle, Loader2 } from "lucide-react";
import {
  fetchDownloadCatalog,
  getDownloadHref,
  type DownloadItem,
} from "../lib/downloads";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DownloadHub() {
  const [items, setItems] = useState<DownloadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const catalog = await fetchDownloadCatalog();
      setItems(catalog);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load downloads");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDownload = (item: DownloadItem) => {
    const href = getDownloadHref(item);
    if (!href) {
      setMessage(
        item.platform === "android"
          ? "APK not built yet. Download the build guide, then build in Android Studio."
          : "Desktop package not built. Run: powershell -File scripts/package_desktop_client.ps1",
      );
      return;
    }
    setMessage(null);
    window.open(href, "_blank", "noopener,noreferrer");
  };

  const iconFor = (platform: string) =>
    platform === "android" ? <Smartphone size={20} /> : <Monitor size={20} />;

  return (
    <div className="glass rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-jarvis-300">Download Hub</div>
        <button
          type="button"
          onClick={() => void load()}
          className="text-xs text-slate-400 hover:text-jarvis-300"
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-400 py-4">
          <Loader2 className="animate-spin" size={16} />
          Loading…
        </div>
      ) : null}

      {error ? (
        <div className="flex gap-2 text-sm text-rose-400 py-2">
          <AlertCircle size={16} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      ) : null}

      {message ? (
        <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          {message}
        </div>
      ) : null}

      <div className="space-y-3">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => handleDownload(item)}
            className="w-full text-left group flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4 transition hover:border-jarvis-500/40 hover:shadow-glow disabled:opacity-70"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-jarvis-500/15 text-jarvis-400">
                {iconFor(item.platform)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-white">{item.title}</div>
                <div className="text-xs text-slate-400">{item.description}</div>
              </div>
              <span
                className={`text-xs font-semibold shrink-0 ${
                  item.available ? "text-emerald-400" : "text-amber-400"
                }`}
              >
                {item.available ? formatSize(item.size_bytes) : "Setup"}
              </span>
            </div>
            <span className="inline-flex items-center gap-2 text-sm font-medium text-jarvis-300 group-hover:text-jarvis-200">
              <Download size={14} />
              {item.available ? "Download" : "Get instructions"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
