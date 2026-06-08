"use client";

import { useCallback, useEffect, useState } from "react";

type AgentStatus = "idle" | "running" | "failed" | "paused" | "spawning" | "completed" | "terminated" | "recovering";

type AgentInfo = {
  agent_id: string;
  agent_type: string;
  status: AgentStatus;
  current_task: string;
  task_count: number;
  error: string;
};

type Summary = {
  total: number;
  running: number;
  idle: number;
  failed: number;
  paused: number;
  other: number;
};

const AGENT_LABELS: Record<string, string> = {
  orchestrator: "Orchestrator",
  code: "Code Writer",
  document: "Document",
  video: "Video",
  os: "OS Control",
  vision: "Vision",
  monitor: "System Monitor",
  deployment: "Deployment",
  testing: "Testing",
  repair: "Repair",
  memory: "Memory",
  security: "Security",
  browser: "Browser",
  research: "Research",
  planner: "Planner",
  worker: "Worker",
};

const AGENT_ICONS: Record<string, string> = {
  orchestrator: "🧠",
  code: "💻",
  document: "📄",
  video: "🎬",
  os: "🖥",
  vision: "👁",
  monitor: "📊",
  deployment: "🚀",
  testing: "🧪",
  repair: "🔧",
  memory: "💾",
  security: "🔒",
  browser: "🌐",
  research: "🔍",
  planner: "📋",
  worker: "⚙",
};

function StatusDot({ status }: { status: AgentStatus }) {
  const colors: Record<string, string> = {
    running: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]",
    idle: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.3)]",
    failed: "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.5)]",
    paused: "bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.3)]",
    spawning: "bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.3)]",
    completed: "bg-emerald-400",
    terminated: "bg-slate-500",
    recovering: "bg-orange-400",
  };
  const pulse = status === "running" ? "animate-pulse" : "";
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${colors[status] || "bg-slate-500"} ${pulse}`}
      title={status}
    />
  );
}

function StatusLabel({ status }: { status: AgentStatus }) {
  const labels: Record<string, string> = {
    running: "Working",
    idle: "Idle",
    failed: "Error",
    paused: "Sleeping",
    spawning: "Starting",
    completed: "Done",
    terminated: "Off",
    recovering: "Recovering",
  };
  const colors: Record<string, string> = {
    running: "text-emerald-400",
    idle: "text-amber-400",
    failed: "text-rose-400",
    paused: "text-sky-400",
    spawning: "text-sky-400",
    completed: "text-emerald-400",
    terminated: "text-slate-500",
    recovering: "text-orange-400",
  };
  return (
    <span className={`text-[10px] font-medium uppercase tracking-wider ${colors[status] || "text-slate-400"}`}>
      {labels[status] || status}
    </span>
  );
}

async function fetchAgentStatus(): Promise<{ agents: AgentInfo[]; summary: Summary }> {
  try {
    const res = await fetch("/api/agents", { cache: "no-store" });
    if (!res.ok) return { agents: [], summary: { total: 0, running: 0, idle: 0, failed: 0, paused: 0, other: 0 } };
    const agents: AgentInfo[] = await res.json();
    const summary: Summary = { total: agents.length, running: 0, idle: 0, failed: 0, paused: 0, other: 0 };
    for (const a of agents) {
      if (a.status in summary) summary[a.status as keyof Summary] += 1;
      else summary.other += 1;
    }
    return { agents, summary };
  } catch {
    return { agents: [], summary: { total: 0, running: 0, idle: 0, failed: 0, paused: 0, other: 0 } };
  }
}

export function AgentStatusGrid() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [summary, setSummary] = useState<Summary>({ total: 0, running: 0, idle: 0, failed: 0, paused: 0, other: 0 });
  const [expanded, setExpanded] = useState(true);

  const refresh = useCallback(async () => {
    const data = await fetchAgentStatus();
    setAgents(data.agents);
    setSummary(data.summary);
  }, []);

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const runningCount = agents.filter((a) => a.status === "running").length;
  const failedCount = agents.filter((a) => a.status === "failed").length;

  return (
    <div className="glass rounded-2xl p-4">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2"
      >
        <div className="flex items-center gap-3">
          <div className="text-lg font-semibold text-white">Subsystem Agents</div>
          {runningCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {runningCount} active
            </span>
          )}
          {failedCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2.5 py-0.5 text-xs font-medium text-rose-400">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
              {failedCount} failed
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>{summary.idle} idle</span>
          <svg
            className={`h-4 w-4 transition-transform ${expanded ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
          {agents.map((agent) => {
            const isWorking = agent.status === "running";
            const hasError = agent.status === "failed";
            return (
              <div
                key={agent.agent_id}
                className={`rounded-xl border p-3 transition-all ${
                  isWorking
                    ? "border-emerald-500/30 bg-emerald-500/5"
                    : hasError
                      ? "border-rose-500/30 bg-rose-500/5"
                      : agent.status === "paused" || agent.status === "spawning"
                        ? "border-sky-500/20 bg-sky-500/5"
                        : "border-slate-700/50 bg-slate-800/30 hover:border-slate-600"
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-base">{AGENT_ICONS[agent.agent_type] || "🤖"}</span>
                  <StatusDot status={agent.status} />
                </div>
                <div className="text-xs font-medium text-white truncate">
                  {AGENT_LABELS[agent.agent_type] || agent.agent_type}
                </div>
                <StatusLabel status={agent.status} />
                {agent.current_task && isWorking && (
                  <div className="mt-1.5 text-[10px] text-slate-400 leading-tight line-clamp-2">
                    {agent.current_task}
                  </div>
                )}
                {hasError && agent.error && (
                  <div className="mt-1.5 text-[10px] text-rose-400 leading-tight line-clamp-1" title={agent.error}>
                    {agent.error}
                  </div>
                )}
                {agent.status === "idle" && (
                  <div className="mt-1.5 text-[10px] text-slate-600">Awaiting tasks</div>
                )}
                {agent.status === "paused" || agent.status === "spawning" ? (
                  <div className="mt-1.5 text-[10px] text-sky-400/60">
                    {agent.status === "spawning" ? "Initializing…" : "Standby"}
                  </div>
                ) : null}
                {agent.task_count > 0 && (
                  <div className="mt-1 text-[10px] text-slate-500">{agent.task_count} tasks</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
