export type ChatResponsePayload = {
  message_id: string;
  conversation_id: string;
  content: string;
  agents_invoked?: string[];
  tasks_created?: string[];
  memories_stored?: string[];
  timestamp?: string;
  audio_base64?: string;
};

export type ConnectedDevice = {
  device_id: string;
  device_name: string;
  device_type: string;
  online?: boolean;
};

export async function postChat(
  token: string | null,
  body: {
    message: string;
    conversation_id?: string;
    device_id?: string;
    include_memory?: boolean;
    stream?: boolean;
    tts_enabled?: boolean;
  },
): Promise<ChatResponsePayload> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch("/api/chat", {
    method: "POST",
    headers,
    body: JSON.stringify({
      include_memory: true,
      stream: false,
      ...body,
    }),
  });

  if (!res.ok) {
    let detail = "";
    try {
      const text = await res.text();
      try {
        const json = JSON.parse(text);
        detail = json.detail || json.message || text;
      } catch {
        detail = text;
      }
    } catch {
      detail = `Chat request failed (${res.status})`;
    }
    throw new Error(detail || `Chat request failed (${res.status})`);
  }

  return res.json();
}

export async function fetchConnectedDevices(token: string | null): Promise<ConnectedDevice[]> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch("/api/droid/devices", {
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    return [];
  }
  const data = await res.json();
  return Array.isArray(data?.devices) ? data.devices : [];
}

export async function generatePairingQr(
  token: string | null,
  desktopDeviceId: string,
): Promise<{
  user_id: string;
  desktop_device_id: string;
  pairing_secret: string;
  base_url: string;
  expires_at: number;
}> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(
    `/api/devices/pair/generate?desktop_device_id=${encodeURIComponent(desktopDeviceId)}`,
    {
      method: "POST",
      headers,
    },
  );
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `Pairing failed (${res.status})`);
  }
  return res.json();
}

export async function ensureDesktopTrusted(
  token: string | null,
  desktopDeviceId: string,
  deviceName: string,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch("/api/devices/pair/register-desktop", {
    method: "POST",
    headers,
    body: JSON.stringify({
      desktop_device_id: desktopDeviceId,
      device_name: deviceName,
      platform: typeof navigator !== "undefined" ? navigator.platform : "web",
    }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `Desktop registration failed (${res.status})`);
  }
}

export type UserSettings = {
  persona: string;
  custom_instructions_a: string;
  custom_instructions_b: string;
};

export async function fetchSettings(userId = "default"): Promise<UserSettings> {
  const res = await fetch(`/api/settings/${userId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load settings (${res.status})`);
  const data = await res.json();
  return {
    persona: data.persona || "adult",
    custom_instructions_a: data.custom_instructions_a || "",
    custom_instructions_b: data.custom_instructions_b || "",
  };
}

export async function saveSettings(
  settings: UserSettings,
  userId = "default",
): Promise<void> {
  const res = await fetch(`/api/settings/${userId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `Failed to save settings (${res.status})`);
  }
}

export type GeneratedMedia = {
  success: boolean;
  file_path: string;
  url: string;
  mime_type: string;
  filename: string;
  size_bytes: number;
  prompt: string;
  model: string;
};

export async function generateImage(
  prompt: string,
  model?: string,
  size?: string,
): Promise<GeneratedMedia> {
  const res = await fetch("/api/media/generate/image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, model, size }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `Image generation failed (${res.status})`);
  }
  return res.json();
}

export async function generateVideo(
  prompt: string,
  model?: string,
  duration?: number,
): Promise<GeneratedMedia> {
  const res = await fetch("/api/media/generate/video", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, model, duration }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `Video generation failed (${res.status})`);
  }
  return res.json();
}

export type MediaFile = {
  filename: string;
  url: string;
  size_bytes: number;
  mime_type: string;
  created_at?: string;
};

// Backwards-compatible alias for older UI code
// (some components expect `createdAt` instead of `created_at`).
export type MediaFileV2 = MediaFile & {
  createdAt?: string;
};

export async function listGeneratedMedia(): Promise<MediaFile[]> {
  const res = await fetch("/api/media/generated", { cache: "no-store" });
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data?.files) ? data.files : [];
}

export async function deleteMedia(filename: string): Promise<boolean> {
  const res = await fetch(`/api/media/generated/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
  return res.ok;
}
