/** FastAPI backend — WebSockets must connect here, not through the Next.js dev server. */
const DEFAULT_BACKEND = "http://localhost:8000";

export function getBackendBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_BACKEND_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  return DEFAULT_BACKEND;
}

export function getWebSocketBaseUrl(): string {
  return getBackendBaseUrl().replace(/^http/i, "ws");
}

/** @deprecated Use fetchDownloadCatalog() from lib/downloads.ts */
export const DOWNLOAD_LINKS = {
  desktopZip: "/api/downloads/jarvis-desktop-windows.zip",
  androidGuide: "/api/downloads/jarvis-android-build-guide.txt",
  androidApk: "/api/downloads/jarvis-android.apk",
};
