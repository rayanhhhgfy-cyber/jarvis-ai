"use client";

import { useCallback, useEffect, useRef, useState, Fragment } from "react";
import { ChevronDown, ChevronUp, Loader2, Mic, MicOff, Send, Terminal, Volume2, VolumeX, X } from "lucide-react";
import { postChat } from "../lib/api";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
};

export type ExecutionLog = {
  id: string;
  command: string;
  device: string;
  status: "success" | "error" | "pending";
  detail: string;
  timestamp: number;
};

type Props = {
  messages: ChatMessage[];
  onMessagesChange: (messages: ChatMessage[]) => void;
  onExecutionResult?: (text: string) => void;
  desktopDeviceId?: string;
  getToken?: () => Promise<string | null>;
};

function isImageUrl(url: string): boolean {
  return /\.(png|jpg|jpeg|gif|webp)(\?.*)?$/i.test(url.split("?")[0].split("#")[0]);
}

function isVideoUrl(url: string): boolean {
  return /\.(mp4|webm|mov)(\?.*)?$/i.test(url.split("?")[0].split("#")[0]);
}

function RenderContent({ content }: { content: string }) {
  const parts = content.split(/(!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)|https?:\/\/\S+)/g);
  return (
    <>
      {parts.map((part, i) => {
        const imgMatch = part.match(/^!\[(.*?)\]\((.*?)\)$/);
        if (imgMatch) {
          const [, alt, url] = imgMatch;
          return isVideoUrl(url) ? (
            <video key={i} controls className="max-w-full rounded-lg my-2 max-h-96" src={url}>
              {alt}
            </video>
          ) : (
            <img key={i} alt={alt} src={url} className="max-w-full rounded-lg my-2 max-h-96 object-contain" loading="lazy" />
          );
        }
        const linkMatch = part.match(/^\[(.*?)\]\((.*?)\)$/);
        if (linkMatch) {
          const [, text, url] = linkMatch;
          if (isImageUrl(url)) {
            return <img key={i} alt={text} src={url} className="max-w-full rounded-lg my-2 max-h-96 object-contain" loading="lazy" />;
          }
          if (isVideoUrl(url)) {
            return <video key={i} controls className="max-w-full rounded-lg my-2 max-h-96" src={url}>{text}</video>;
          }
          return <a key={i} href={url} target="_blank" rel="noopener noreferrer" className="text-jarvis-400 underline">{text}</a>;
        }
        const isUrl = /^https?:\/\/\S+$/i.test(part);
        if (isUrl) {
          if (isImageUrl(part)) {
            return <img key={i} alt="" src={part} className="max-w-full rounded-lg my-2 max-h-96 object-contain" loading="lazy" />;
          }
          if (isVideoUrl(part)) {
            return <video key={i} controls className="max-w-full rounded-lg my-2 max-h-96" src={part} />;
          }
          return <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="text-jarvis-400 underline break-all">{part}</a>;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex h-8 items-end gap-1" aria-hidden={!active}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className={`w-1 rounded-full bg-jarvis-400 ${
            active ? "animate-pulse" : "opacity-30"
          }`}
          style={{
            height: active ? `${12 + (i % 3) * 8}px` : "8px",
            animationDelay: `${i * 0.1}s`,
          }}
        />
      ))}
    </div>
  );
}

export function ChatPanel({
  messages,
  onMessagesChange,
  onExecutionResult,
  desktopDeviceId = "",
  getToken,
}: Props) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string>("");
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [logsExpanded, setLogsExpanded] = useState(true);
  const [recording, setRecording] = useState(false);
  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(null);
  const [muted, setMuted] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, executionLogs]);

  const appendLog = useCallback((log: Omit<ExecutionLog, "id" | "timestamp">) => {
    setExecutionLogs((prev) => [
      ...prev,
      { ...log, id: crypto.randomUUID(), timestamp: Date.now() },
    ]);
  }, []);

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: trimmed,
        timestamp: Date.now(),
      };
      onMessagesChange([...messages, userMsg]);
      setInput("");
      setLoading(true);

      appendLog({
        command: trimmed,
        device: "server",
        status: "pending",
        detail: "Dispatching to Jarvis backend…",
      });

      try {
        const token = getToken ? await getToken() : null;

        const data = await postChat(token, {
          message: trimmed,
          conversation_id: conversationId || undefined,
          device_id: desktopDeviceId,
          include_memory: true,
          stream: false,
          tts_enabled: !muted,
        });

        if (data.conversation_id) setConversationId(data.conversation_id);

        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.content || "No response.",
          timestamp: Date.now(),
        };
        onMessagesChange([...messages, userMsg, assistantMsg]);
        onExecutionResult?.(data.content || "");

        // Play TTS audio if available and not muted
        if (!muted && data.audio_base64) {
          try {
            const audioSrc = "data:audio/wav;base64," + data.audio_base64;
            if (audioRef.current) {
              audioRef.current.src = audioSrc;
              audioRef.current.play().catch(() => {});
            }
          } catch {
            // Audio playback failed silently
          }
        }

        setExecutionLogs((prev) => {
          const next = [...prev];
          const idx = next.findIndex((l) => l.status === "pending");
          if (idx >= 0) {
            next[idx] = {
              ...next[idx],
              status: "success",
              detail: data.tasks_created?.length
                ? `Tasks: ${data.tasks_created.join(", ")}`
                : "Completed",
            };
          }
          return next;
        });

        if (data.tasks_created?.length) {
          for (const taskId of data.tasks_created) {
            appendLog({
              command: trimmed,
              device: "workstation",
              status: "success",
              detail: `Task queued: ${taskId}`,
            });
          }
        }
      } catch (e: unknown) {
        const err = e instanceof Error ? e.message : "Request failed";
        const errMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `I encountered an error, Sir: ${err}${err.includes("500") ? "\n\nCheck the backend terminal for the full error traceback." : ""}`,
          timestamp: Date.now(),
        };
        onMessagesChange([...messages, userMsg, errMsg]);
        setExecutionLogs((prev) => {
          const next = [...prev];
          const idx = next.findIndex((l) => l.status === "pending");
          if (idx >= 0) {
            next[idx] = { ...next[idx], status: "error", detail: err };
          }
          return next;
        });
      } finally {
        setLoading(false);
      }
    },
    [
      loading,
      messages,
      onMessagesChange,
      onExecutionResult,
      getToken,
      conversationId,
      desktopDeviceId,
      appendLog,
    ],
  );

  const toggleRecording = async () => {
    if (recording && mediaRecorder) {
      mediaRecorder.stop();
      setRecording(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];

      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunks.push(ev.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: "audio/webm" });
        appendLog({
          command: "voice_input",
          device: "microphone",
          status: "success",
          detail: `Captured ${Math.round(blob.size / 1024)}KB audio (transcription via /api/audio when configured)`,
        });
        await sendText("[Voice message recorded — configure /api/audio for transcription]");
      };

      recorder.start();
      setMediaRecorder(recorder);
      setRecording(true);
    } catch {
      appendLog({
        command: "voice_input",
        device: "microphone",
        status: "error",
        detail: "Microphone permission denied or unavailable",
      });
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-jarvis-300 text-sm font-semibold">Jarvis Chat</div>
          <div className="text-white text-xl font-bold">Command &amp; control</div>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="animate-spin" size={16} />
            Processing…
          </div>
        ) : null}
      </div>

      <div className="max-h-[420px] overflow-y-auto rounded-xl border border-slate-800 bg-slate-900/30 p-4 space-y-3">
        {messages.length === 0 ? (
          <div className="text-sm text-slate-500 text-center py-8">
            Ask Jarvis to open apps, send messages, or run commands on your phone or PC.
          </div>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                  m.role === "user"
                    ? "bg-jarvis-600/30 text-white border border-jarvis-500/30"
                    : "bg-slate-800/80 text-slate-100 border border-slate-700"
                }`}
              >
                <RenderContent content={m.content} />
              </div>
            </div>
          ))
        )}
        {loading ? (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-slate-800/60 px-4 py-3 border border-slate-700">
              <div className="flex gap-2">
                <span className="h-2 w-2 rounded-full bg-jarvis-400 animate-bounce" />
                <span className="h-2 w-2 rounded-full bg-jarvis-400 animate-bounce [animation-delay:0.15s]" />
                <span className="h-2 w-2 rounded-full bg-jarvis-400 animate-bounce [animation-delay:0.3s]" />
              </div>
            </div>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      {executionLogs.length > 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
          <button
            onClick={() => setLogsExpanded((v) => !v)}
            className="flex w-full items-center justify-between gap-2 text-xs font-semibold text-slate-400 mb-2"
          >
            <div className="flex items-center gap-2">
              <Terminal size={14} />
              Execution log ({executionLogs.length})
            </div>
            <div className="flex items-center gap-1">
              <span
                role="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setExecutionLogs([]);
                }}
                className="rounded p-1 text-slate-600 hover:text-slate-300 hover:bg-slate-800/60"
              >
                <X size={14} />
              </span>
              {logsExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </div>
          </button>
          {logsExpanded && (
            <div className="space-y-2 max-h-32 overflow-y-auto">
              {executionLogs.slice(-8).map((log) => (
                <div
                  key={log.id}
                  className="flex items-start justify-between gap-2 text-xs border-b border-slate-800/80 pb-2 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="text-slate-200 truncate">{log.command}</div>
                    <div className="text-slate-500">{log.device} &bull; {log.detail}</div>
                  </div>
                  <span
                    className={
                      log.status === "success"
                        ? "text-emerald-400"
                        : log.status === "error"
                          ? "text-rose-400"
                          : "text-yellow-400"
                    }
                  >
                    {log.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}

      <audio ref={audioRef} className="hidden" />
      <div className="flex items-end gap-2">
        <button
          type="button"
          onClick={() => setMuted((v) => !v)}
          className={`shrink-0 rounded-xl p-3 border ${
            muted
              ? "border-slate-600 bg-slate-800/50 text-slate-400"
              : "border-slate-700 bg-slate-900/50 text-jarvis-300 hover:border-jarvis-500/40"
          }`}
          aria-label={muted ? "Unmute" : "Mute"}
          title={muted ? "Unmute JARVIS voice" : "Mute JARVIS voice"}
        >
          {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <button
          type="button"
          onClick={toggleRecording}
          className={`shrink-0 rounded-xl p-3 border ${
            recording
              ? "border-rose-500/50 bg-rose-500/10 text-rose-400"
              : "border-slate-700 bg-slate-900/50 text-slate-300 hover:border-jarvis-500/40"
          }`}
          aria-label={recording ? "Stop recording" : "Start recording"}
        >
          {recording ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
        <div className="flex-1 rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
          {recording ? (
            <div className="flex items-center gap-3 py-1">
              <Waveform active />
              <span className="text-xs text-jarvis-300">Listening…</span>
            </div>
          ) : (
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendText(input);
                }
              }}
              rows={2}
              placeholder="Jarvis, open Visual Studio Code on my computer…"
              className="w-full resize-none bg-transparent text-sm text-slate-100 placeholder:text-slate-500 outline-none"
            />
          )}
        </div>
        <button
          type="button"
          disabled={loading || !input.trim()}
          onClick={() => void sendText(input)}
          className="shrink-0 rounded-xl p-3 bg-jarvis-500 hover:bg-jarvis-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label="Send message"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
