/**
 * Singleton UI WebSocket — avoids duplicate connections from React Strict Mode.
 */

import { getWebSocketBaseUrl } from "./config";

export type WsStatus = "disconnected" | "connecting" | "connected";

type Listener = (status: WsStatus, error: string | null) => void;
type MessageListener = (msg: Record<string, unknown>) => void;

let socket: WebSocket | null = null;
let status: WsStatus = "disconnected";
let lastError: string | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let listeners = new Set<Listener>();
let messageListeners = new Set<MessageListener>();
let refCount = 0;
let intentionalClose = false;

function notify() {
  for (const fn of listeners) {
    fn(status, lastError);
  }
}

function clearTimers() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect() {
  if (intentionalClose || refCount <= 0) return;
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 3000);
}

function connect() {
  if (intentionalClose || refCount <= 0) return;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const wsUrl = `${getWebSocketBaseUrl()}/ws/ui`;
  status = "connecting";
  lastError = null;
  notify();

  try {
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      if (intentionalClose) return;
      status = "connected";
      lastError = null;
      notify();
      try {
        socket?.send(JSON.stringify({ type: "ping" }));
      } catch {
        // ignore
      }
      clearTimers();
      heartbeatTimer = setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          try {
            socket.send(JSON.stringify({ type: "ping" }));
          } catch {
            // ignore
          }
        }
      }, 25000);
    };

    socket.onerror = () => {
      if (intentionalClose) return;
      lastError = `Cannot reach ${wsUrl} — is the backend running on port 8000?`;
      status = "disconnected";
      notify();
    };

    socket.onclose = (ev) => {
      clearTimers();
      socket = null;
      if (intentionalClose) return;
      status = "disconnected";
      if (ev.code !== 1000) {
        lastError =
          lastError ||
          `Connection lost (code ${ev.code}). Restart: python -m uvicorn backend.main:app --port 8000`;
      }
      notify();
      scheduleReconnect();
    };

    socket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as Record<string, unknown>;
        if (msg.type === "system_status" || msg.type === "pong") {
          status = "connected";
          lastError = null;
          notify();
        }
        for (const fn of messageListeners) {
          try { fn(msg); } catch { /* ignore */ }
        }
      } catch {
        // ignore
      }
    };
  } catch (e: unknown) {
    status = "disconnected";
    lastError = e instanceof Error ? e.message : "WebSocket failed";
    notify();
    scheduleReconnect();
  }
}

export function subscribeJarvisWs(listener: Listener): () => void {
  refCount += 1;
  intentionalClose = false;
  listeners.add(listener);
  listener(status, lastError);
  connect();

  return () => {
    listeners.delete(listener);
    refCount -= 1;
    if (refCount <= 0) {
      refCount = 0;
      intentionalClose = true;
      clearTimers();
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      try {
        socket?.close(1000, "no_subscribers");
      } catch {
        // ignore
      }
      socket = null;
      status = "disconnected";
    }
  };
}

export function getJarvisWsStatus(): { status: WsStatus; error: string | null } {
  return { status, error: lastError };
}

export function addMessageListener(fn: MessageListener): () => void {
  messageListeners.add(fn);
  return () => { messageListeners.delete(fn); };
}
