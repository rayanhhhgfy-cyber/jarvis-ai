import { getBackendBaseUrl } from "./config";

export type DownloadItem = {
  id: string;
  filename: string;
  title: string;
  description: string;
  platform: string;
  available: boolean;
  size_bytes: number;
  download_url: string | null;
};

export async function fetchDownloadCatalog(): Promise<DownloadItem[]> {
  const res = await fetch(`${getBackendBaseUrl()}/api/downloads`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Could not load download list — is the backend running?");
  }
  const data = (await res.json()) as { items?: DownloadItem[] };
  return Array.isArray(data.items) ? data.items : [];
}

export function getDownloadHref(item: DownloadItem): string {
  if (!item.available || !item.download_url) return "";
  if (item.download_url.startsWith("http")) return item.download_url;
  return `${getBackendBaseUrl()}${item.download_url}`;
}
