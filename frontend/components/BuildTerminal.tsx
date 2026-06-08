"use client";

import React, { useEffect, useRef, useState } from "react";
import { Terminal, Maximize2, Minimize2, Trash2, PlugZap } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface BuildTerminalProps {
  projectId: string | null;
  logs: string[];
}

/* ------------------------------------------------------------------ */
/*  ANSI-lite colouring (for npm output highlighting)                  */
/* ------------------------------------------------------------------ */

function colorize(line: string): React.ReactNode {
  // Simple pattern matching for common log patterns
  if (line.startsWith("[JARVIS]")) {
    return <span className="text-jarvis-400 font-medium">{line}</span>;
  }
  if (/error/i.test(line) && !/\d+ error/.test(line)) {
    return <span className="text-red-400">{line}</span>;
  }
  if (/warn(ing)?/i.test(line)) {
    return <span className="text-amber-400">{line}</span>;
  }
  if (/success|ready|compiled/i.test(line)) {
    return <span className="text-emerald-400">{line}</span>;
  }
  if (line.startsWith("$") || line.startsWith(">")) {
    return <span className="text-sky-400">{line}</span>;
  }
  return <span className="text-slate-400">{line}</span>;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function BuildTerminal({ projectId, logs }: BuildTerminalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [wsLogs, setWsLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, wsLogs]);

  // WebSocket live logs
  useEffect(() => {
    if (!projectId) return;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(`${proto}//${host}/api/build/ws/logs/${projectId}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      setWsLogs((prev) => {
        const next = [...prev, e.data];
        return next.length > 500 ? next.slice(-500) : next;
      });
    };

    ws.onerror = () => {};
    ws.onclose = () => { wsRef.current = null; };

    return () => {
      ws.close();
    };
  }, [projectId]);

  const allLogs = [...logs, ...wsLogs];
  const clearLogs = () => setWsLogs([]);

  return (
    <div
      className={`flex flex-col border-t border-slate-800/80 bg-[#0a0e1a] transition-all duration-300 ${
        expanded ? "h-[50vh]" : "h-48"
      }`}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-slate-800/60 px-3 py-1.5">
        <div className="flex items-center gap-2 text-[12px]">
          <Terminal size={13} className="text-slate-500" />
          <span className="font-medium text-slate-400">Build Terminal</span>
          {projectId && (
            <>
              <span className="text-slate-700">•</span>
              <span className="font-mono text-[11px] text-slate-600">{projectId}</span>
            </>
          )}
          {wsRef.current?.readyState === WebSocket.OPEN && (
            <span className="flex items-center gap-1 text-[10px] text-emerald-500">
              <PlugZap size={10} />
              Live
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={clearLogs}
            className="rounded p-1 text-slate-600 hover:bg-slate-800 hover:text-slate-400 transition-colors"
            title="Clear logs"
          >
            <Trash2 size={12} />
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="rounded p-1 text-slate-600 hover:bg-slate-800 hover:text-slate-400 transition-colors"
            title={expanded ? "Minimize" : "Maximize"}
          >
            {expanded ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
          </button>
        </div>
      </div>

      {/* Log output */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-2 font-mono text-[12px] leading-5 custom-scrollbar"
      >
        {allLogs.length === 0 ? (
          <div className="flex h-full items-center justify-center text-slate-700 text-[11px]">
            {projectId
              ? "Waiting for build output..."
              : "Generate a project, then run the dev server to see logs here."}
          </div>
        ) : (
          allLogs.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              {colorize(line)}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
