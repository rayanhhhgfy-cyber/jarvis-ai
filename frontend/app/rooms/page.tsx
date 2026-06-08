"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Layers, RefreshCw, Loader2, CheckCircle, XCircle, Clock, Activity, Zap,
  GitBranch, AlertCircle, Plus, Trash2, Play, Edit3, Calendar,
  ChevronDown, ChevronUp, Sparkles, Ban, Save, Terminal,
} from "lucide-react";

type Task = {
  task_id: string;
  title: string;
  description: string;
  agent_type: string;
  priority: "critical" | "high" | "medium" | "low";
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

type Workflow = {
  workflow_id: string;
  name: string;
  description: string;
  commands: string[];
  step_count: number;
  created_at: string;
  updated_at: string;
  run_count: number;
  cron?: string;
};

type Pattern = {
  pattern_key: string;
  frequency: number;
  sequence_length: number;
  commands: string[];
  command_types: string[];
  suggest_workflow: boolean;
};

type Stats = {
  total_commands_recorded: number;
  patterns_detected: number;
  workflows_created: number;
  high_frequency_patterns: Pattern[];
  recent_commands: { command: string; timestamp: string; success: boolean }[];
};

const PRIORITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };
const PRIORITY_COLORS: Record<string, string> = {
  critical: "text-red-400 border-red-800/40 bg-red-950/40",
  high: "text-orange-400 border-orange-800/40 bg-orange-950/40",
  medium: "text-yellow-400 border-yellow-800/40 bg-yellow-950/40",
  low: "text-slate-400 border-slate-700/40 bg-slate-800/40",
};
const STATUS_COLORS: Record<string, string> = {
  queued: "text-slate-400",
  assigned: "text-blue-400",
  running: "text-emerald-400",
  completed: "text-green-400",
  failed: "text-red-400",
  cancelled: "text-slate-500",
  awaiting_approval: "text-yellow-400",
};

function api(path: string, opts?: RequestInit) {
  return fetch(path, { ...opts, cache: "no-store" });
}

export default function RoomsPage() {
  const [agents, setAgents] = useState<any[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"tasks" | "workflows" | "patterns">("tasks");
  const [showCreateTask, setShowCreateTask] = useState(false);
  const [newTask, setNewTask] = useState({ title: "", description: "", priority: "medium" });
  const [showCreateWorkflow, setShowCreateWorkflow] = useState(false);
  const [newWorkflow, setNewWorkflow] = useState({ name: "", description: "", commands: "", cron: "" });
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [editWfData, setEditWfData] = useState({ name: "", description: "", commands: "", cron: "" });
  const [nextTask, setNextTask] = useState<Task | null>(null);
  const [editingTask, setEditingTask] = useState<string | null>(null);
  const [editTaskData, setEditTaskData] = useState({ title: "", description: "", priority: "medium" });
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const showFeedback = (type: "success" | "error", message: string) => {
    setFeedback({ type, message });
    setTimeout(() => setFeedback(null), 4000);
  };

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [aRes, tRes, wRes, sRes, nRes] = await Promise.allSettled([
        api("/api/agents/summary"),
        api("/api/tasks"),
        api("/api/patterns/workflows"),
        api("/api/patterns/stats"),
        api("/api/tasks/next"),
      ]);

      if (aRes.status === "fulfilled" && aRes.value.ok) {
        const data = await aRes.value.json();
        setAgents(data.agents || []);
      }
      if (tRes.status === "fulfilled" && tRes.value.ok) {
        const data = await tRes.value.json();
        setTasks(Array.isArray(data) ? data : []);
      }
      if (wRes.status === "fulfilled" && wRes.value.ok) {
        const data = await wRes.value.json();
        setWorkflows(data.workflows || []);
      }
      if (sRes.status === "fulfilled" && sRes.value.ok) {
        setStats(await sRes.value.json());
      }
      if (nRes.status === "fulfilled" && nRes.value.ok) {
        const data = await nRes.value.json();
        setNextTask(data.task || null);
      }
    } catch {
      setError("Failed to load rooms data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const createTask = async () => {
    if (!newTask.title.trim()) return;
    await api("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: newTask.title,
        description: newTask.description,
        priority: newTask.priority,
        agent_type: "worker",
      }),
    });
    setNewTask({ title: "", description: "", priority: "medium" });
    setShowCreateTask(false);
    loadAll();
  };

  const updateTaskStatus = async (taskId: string, status: string) => {
    await api(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    loadAll();
  };

  const updateTaskPriority = async (taskId: string, priority: string) => {
    await api(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority }),
    });
    loadAll();
  };

  const saveEditTask = async (taskId: string) => {
    await api(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editTaskData),
    });
    setEditingTask(null);
    loadAll();
  };

  const deleteTask = async (taskId: string) => {
    await api(`/api/tasks/${taskId}`, { method: "DELETE" });
    loadAll();
  };

  const createWorkflow = async () => {
    const commands = newWorkflow.commands.split("\n").filter(Boolean);
    if (commands.length === 0) return;
    await api("/api/patterns/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: newWorkflow.name || "Custom Workflow",
        description: newWorkflow.description,
        commands,
        cron: newWorkflow.cron || undefined,
      }),
    });
    setNewWorkflow({ name: "", description: "", commands: "", cron: "" });
    setShowCreateWorkflow(false);
    loadAll();
  };

  const runWorkflow = async (wfId: string) => {
    await api(`/api/patterns/workflows/${wfId}/run`, { method: "POST" });
  };

  const deleteWorkflow = async (wfId: string) => {
    await api(`/api/patterns/workflows/${wfId}`, { method: "DELETE" });
    loadAll();
  };

  const saveEditWorkflow = async () => {
    if (!editingWorkflow) return;
    const commands = editWfData.commands.split("\n").filter(Boolean);
    if (commands.length === 0) return;
    await api(`/api/patterns/workflows/${editingWorkflow.workflow_id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: editWfData.name,
        description: editWfData.description,
        commands,
        cron: editWfData.cron || null,
      }),
    });
    setEditingWorkflow(null);
    loadAll();
  };

  const suggestWorkflow = async () => {
    const res = await api("/api/patterns/suggest", { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      if (data.suggested) {
        showFeedback("success", `Workflow "${data.workflow.name}" created from pattern seen ${data.pattern.frequency} times`);
        loadAll();
      } else {
        showFeedback("error", data.message || "Not enough pattern data yet — repeat a command sequence 3+ times first");
      }
    } else {
      showFeedback("error", "Pattern detection endpoint unavailable");
    }
  };

  const scheduleWorkflow = async (wfId: string, cron: string) => {
    await api(`/api/patterns/workflows/${wfId}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cron }),
    });
    loadAll();
  };

  const openEditWorkflow = (wf: Workflow) => {
    setEditingWorkflow(wf);
    setEditWfData({
      name: wf.name,
      description: wf.description,
      commands: (wf.commands || []).join("\n"),
      cron: wf.cron || "",
    });
  };

  const openEditTask = (t: Task) => {
    setEditingTask(t.task_id);
    setEditTaskData({ title: t.title, description: t.description, priority: t.priority });
  };

  const nextStatus = (s: string): string | null => {
    if (s === "queued") return "running";
    if (s === "running") return "completed";
    if (s === "completed" || s === "failed") return null;
    if (s === "assigned") return "running";
    return "running";
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="animate-spin text-slate-500" size={32} />
      </div>
    );
  }

  const sortedTasks = [...tasks].sort((a, b) => {
    const pa = PRIORITY_ORDER[a.priority] ?? 99;
    const pb = PRIORITY_ORDER[b.priority] ?? 99;
    if (pa !== pb) return pa - pb;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  const incompleteTasks = sortedTasks.filter(t => !["completed", "cancelled", "failed"].includes(t.status));
  const completedTasks = sortedTasks.filter(t => ["completed", "cancelled", "failed"].includes(t.status));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Command Rooms</h1>
          <p className="text-sm text-slate-400 mt-1">
            {agents.length} agents · {incompleteTasks.length} active tasks · {workflows.length} workflows
          </p>
        </div>
        <button onClick={loadAll} className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors">
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-800/50 bg-red-900/20 px-4 py-3 text-sm text-red-400">{error}</div>
      )}
      {feedback && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${
          feedback.type === "success"
            ? "border-emerald-800/50 bg-emerald-900/20 text-emerald-400"
            : "border-yellow-800/50 bg-yellow-900/20 text-yellow-400"
        }`}>
          {feedback.type === "success" ? "✓ " : "ⓘ "}{feedback.message}
        </div>
      )}

      {/* Next Task Banner */}
      {nextTask && (
        <div className="rounded-lg border border-jarvis-800/40 bg-jarvis-950/20 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Sparkles size={18} className="text-jarvis-400" />
            <div>
              <span className="text-sm font-medium text-slate-200">Next Priority Task: </span>
              <span className="text-sm text-slate-300">{nextTask.title}</span>
              <span className={`ml-2 text-xs ${PRIORITY_COLORS[nextTask.priority]?.split(" ")[0] || "text-slate-400"}`}>
                {nextTask.priority}
              </span>
            </div>
          </div>
          <button onClick={() => updateTaskStatus(nextTask.task_id, "running")} className="flex items-center gap-1.5 rounded-lg bg-emerald-700/30 border border-emerald-700/50 px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-700/50">
            <Play size={12} /> Start Now
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-4 border-b border-slate-800 pb-0">
        {([
          ["tasks", "Tasks", Layers],
          ["workflows", "Workflows", GitBranch],
          ["patterns", "Patterns", Sparkles],
        ] as const).map(([key, label, Icon]) => (
          <button key={key} onClick={() => setActiveTab(key)} className={`flex items-center gap-2 pb-3 text-sm border-b-2 transition-colors ${
            activeTab === key ? "border-jarvis-400 text-jarvis-300" : "border-transparent text-slate-500 hover:text-slate-300"
          }`}>
            <Icon size={16} />
            {label}
            {key === "tasks" && incompleteTasks.length > 0 && (
              <span className="bg-jarvis-500/20 text-jarvis-300 text-[10px] px-1.5 py-0.5 rounded-full">{incompleteTasks.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* ===== TASKS TAB ===== */}
      {activeTab === "tasks" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-200">Active Tasks ({incompleteTasks.length})</h2>
            <button onClick={() => setShowCreateTask(!showCreateTask)} className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50">
              <Plus size={14} /> New Task
            </button>
          </div>

          {showCreateTask && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 space-y-3">
              <input
                value={newTask.title} onChange={e => setNewTask(p => ({ ...p, title: e.target.value }))}
                placeholder="Task title..."
                className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-jarvis-500"
                onKeyDown={e => { if (e.key === "Enter") createTask(); }}
              />
              <textarea
                value={newTask.description} onChange={e => setNewTask(p => ({ ...p, description: e.target.value }))}
                placeholder="Description (optional)..."
                rows={2}
                className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-jarvis-500 resize-none"
              />
              <div className="flex items-center gap-3">
                <select value={newTask.priority} onChange={e => setNewTask(p => ({ ...p, priority: e.target.value }))}
                  className="rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-jarvis-500">
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
                <button onClick={createTask} className="rounded-lg bg-jarvis-600 hover:bg-jarvis-500 px-4 py-2 text-sm text-white transition-colors">
                  Create Task
                </button>
                <button onClick={() => setShowCreateTask(false)} className="text-xs text-slate-500 hover:text-slate-300">Cancel</button>
              </div>
            </div>
          )}

          {incompleteTasks.length === 0 && !showCreateTask ? (
            <p className="text-sm text-slate-500 py-8 text-center">No active tasks. Create one to get started!</p>
          ) : (
            <div className="space-y-2">
              {incompleteTasks.map(t => {
                const nextSt = nextStatus(t.status);
                const isEditing = editingTask === t.task_id;
                return (
                  <div key={t.task_id} className={`rounded-lg border ${PRIORITY_COLORS[t.priority] || "border-slate-800 bg-slate-900/60"} p-3`}>
                    {isEditing ? (
                      <div className="space-y-2">
                        <input value={editTaskData.title} onChange={e => setEditTaskData(p => ({ ...p, title: e.target.value }))}
                          className="w-full rounded border border-slate-700 bg-slate-900/80 px-2 py-1.5 text-sm text-slate-200" />
                        <textarea value={editTaskData.description} onChange={e => setEditTaskData(p => ({ ...p, description: e.target.value }))}
                          rows={2} className="w-full rounded border border-slate-700 bg-slate-900/80 px-2 py-1.5 text-sm text-slate-200 resize-none" />
                        <div className="flex gap-2">
                          <select value={editTaskData.priority} onChange={e => setEditTaskData(p => ({ ...p, priority: e.target.value }))}
                            className="rounded border border-slate-700 bg-slate-900/80 px-2 py-1 text-xs text-slate-200">
                            <option value="critical">Critical</option>
                            <option value="high">High</option>
                            <option value="medium">Medium</option>
                            <option value="low">Low</option>
                          </select>
                          <button onClick={() => saveEditTask(t.task_id)} className="rounded bg-green-700/50 px-2.5 py-1 text-xs text-green-300 hover:bg-green-700/70">
                            <Save size={12} />
                          </button>
                          <button onClick={() => setEditingTask(null)} className="text-xs text-slate-500 hover:text-slate-300">Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-200">{t.title}</span>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${PRIORITY_COLORS[t.priority] || ""}`}>
                                {t.priority}
                              </span>
                              <span className={`text-[10px] capitalize ${STATUS_COLORS[t.status] || "text-slate-400"}`}>
                                {t.status}
                              </span>
                            </div>
                            {t.description && <p className="text-xs text-slate-400 mt-1 line-clamp-2">{t.description}</p>}
                          </div>
                          <div className="flex items-center gap-1 shrink-0 ml-3">
                            {nextSt && (
                              <button onClick={() => updateTaskStatus(t.task_id, nextSt)} title={`Mark ${nextSt}`}
                                className="rounded p-1.5 text-slate-500 hover:bg-slate-700/50 hover:text-slate-200">
                                {nextSt === "running" ? <Play size={13} /> : <CheckCircle size={13} />}
                              </button>
                            )}
                            <button onClick={() => openEditTask(t)} className="rounded p-1.5 text-slate-500 hover:bg-slate-700/50 hover:text-slate-200">
                              <Edit3 size={13} />
                            </button>
                            <button onClick={() => deleteTask(t.task_id)} className="rounded p-1.5 text-slate-500 hover:bg-red-900/30 hover:text-red-400">
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 mt-1.5 text-[10px] text-slate-600">
                          {t.created_at && <span>{new Date(t.created_at).toLocaleString()}</span>}
                          <select value={t.priority} onChange={e => updateTaskPriority(t.task_id, e.target.value)}
                            className="bg-transparent border border-slate-700 rounded px-1 py-0.5 text-[10px] text-slate-400 cursor-pointer hover:border-slate-500">
                            <option value="critical">Critical</option>
                            <option value="high">High</option>
                            <option value="medium">Medium</option>
                            <option value="low">Low</option>
                          </select>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {completedTasks.length > 0 && (
            <>
              <h3 className="text-sm font-medium text-slate-500 pt-4">Completed ({completedTasks.length})</h3>
              <div className="space-y-1">
                {completedTasks.slice(0, 5).map(t => (
                  <div key={t.task_id} className="flex items-center justify-between rounded-lg px-3 py-2 bg-slate-900/30 border border-slate-800/50">
                    <div className="flex items-center gap-2 min-w-0">
                      <CheckCircle size={12} className="text-green-600 shrink-0" />
                      <span className="text-xs text-slate-400 truncate">{t.title}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[10px] ${STATUS_COLORS[t.status] || "text-slate-500"}`}>{t.status}</span>
                      <button onClick={() => deleteTask(t.task_id)} className="rounded p-1 text-slate-600 hover:text-red-400">
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ===== WORKFLOWS TAB ===== */}
      {activeTab === "workflows" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-200">
              Workflows ({workflows.length})
              {stats && stats.workflows_created > 0 && (
                <span className="ml-2 text-xs text-slate-500 font-normal">{stats.workflows_created} total created</span>
              )}
            </h2>
            <button onClick={() => setShowCreateWorkflow(!showCreateWorkflow)} className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50">
              <Plus size={14} /> New Workflow
            </button>
          </div>

          {showCreateWorkflow && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 space-y-3">
              <input value={newWorkflow.name} onChange={e => setNewWorkflow(p => ({ ...p, name: e.target.value }))}
                placeholder="Workflow name..."
                className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-jarvis-500"
              />
              <textarea value={newWorkflow.description} onChange={e => setNewWorkflow(p => ({ ...p, description: e.target.value }))}
                placeholder="Description..."
                rows={2}
                className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-jarvis-500 resize-none"
              />
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Commands (one per line):</label>
                <textarea value={newWorkflow.commands} onChange={e => setNewWorkflow(p => ({ ...p, commands: e.target.value }))}
                  placeholder={`desktop_launch_app|chrome\nsearch_web|daily news`}
                  rows={4}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs text-slate-200 font-mono placeholder-slate-600 focus:outline-none focus:border-jarvis-500 resize-none"
                />
              </div>
              <div className="flex items-center gap-3">
                <input value={newWorkflow.cron} onChange={e => setNewWorkflow(p => ({ ...p, cron: e.target.value }))}
                  placeholder="Cron (e.g. 55 17 * * * for 5:55 PM daily)"
                  className="flex-1 rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-jarvis-500 font-mono"
                />
                <button onClick={createWorkflow} className="rounded-lg bg-jarvis-600 hover:bg-jarvis-500 px-4 py-2 text-sm text-white transition-colors">
                  <Save size={14} />
                </button>
                <button onClick={() => setShowCreateWorkflow(false)} className="text-xs text-slate-500 hover:text-slate-300">Cancel</button>
              </div>
            </div>
          )}

          {editingWorkflow && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 space-y-3">
              <h3 className="text-sm font-medium text-slate-200">Edit Workflow</h3>
              <input value={editWfData.name} onChange={e => setEditWfData(p => ({ ...p, name: e.target.value }))}
                placeholder="Name"
                className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-jarvis-500"
              />
              <textarea value={editWfData.description} onChange={e => setEditWfData(p => ({ ...p, description: e.target.value }))}
                placeholder="Description" rows={2}
                className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-jarvis-500 resize-none"
              />
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Commands (one per line):</label>
                <textarea value={editWfData.commands} onChange={e => setEditWfData(p => ({ ...p, commands: e.target.value }))}
                  rows={4}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-jarvis-500 resize-none"
                />
              </div>
              <div className="flex items-center gap-3">
                <input value={editWfData.cron} onChange={e => setEditWfData(p => ({ ...p, cron: e.target.value }))}
                  placeholder="Cron (e.g. 55 17 * * *)"
                  className="flex-1 rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-jarvis-500"
                />
                <button onClick={saveEditWorkflow} className="rounded-lg bg-green-700/50 hover:bg-green-600/70 px-3 py-2 text-xs text-green-300">
                  <Save size={14} />
                </button>
                <button onClick={() => setEditingWorkflow(null)} className="text-xs text-slate-500 hover:text-slate-300">Cancel</button>
              </div>
            </div>
          )}

          {workflows.length === 0 && !showCreateWorkflow ? (
            <p className="text-sm text-slate-500 py-8 text-center">
              No workflows defined. Patterns will auto-suggest workflows as you use commands, or create one manually.
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {workflows.map(w => (
                <div key={w.workflow_id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 hover:border-slate-700 transition-colors">
                  <div className="flex items-start justify-between mb-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <GitBranch size={14} className="text-jarvis-400 shrink-0" />
                        <span className="text-sm font-medium text-slate-200 truncate">{w.name}</span>
                      </div>
                      {w.description && <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-1">{w.description}</p>}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    <span className="text-[10px] text-slate-500 bg-slate-800/50 px-1.5 py-0.5 rounded">
                      {w.step_count || w.commands?.length || 0} steps
                    </span>
                    {w.run_count > 0 && (
                      <span className="text-[10px] text-emerald-500 bg-emerald-950/30 px-1.5 py-0.5 rounded">
                        {w.run_count}x run
                      </span>
                    )}
                    {w.cron && (
                      <span className="text-[10px] text-jarvis-400 bg-jarvis-950/30 px-1.5 py-0.5 rounded font-mono">
                        {w.cron}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => runWorkflow(w.workflow_id)} title="Run now"
                      className="flex items-center gap-1 rounded bg-emerald-700/20 border border-emerald-700/30 px-2 py-1 text-[10px] text-emerald-400 hover:bg-emerald-700/40">
                      <Play size={10} /> Run
                    </button>
                    <button onClick={() => openEditWorkflow(w)} title="Edit"
                      className="rounded p-1 text-slate-500 hover:bg-slate-700/50 hover:text-slate-200">
                      <Edit3 size={12} />
                    </button>
                    <button onClick={() => deleteWorkflow(w.workflow_id)} title="Delete"
                      className="rounded p-1 text-slate-500 hover:bg-red-900/30 hover:text-red-400">
                      <Trash2 size={12} />
                    </button>
                    {!w.cron && (
                      <button onClick={() => {
                        const cron = prompt("Enter cron expression (e.g. 55 17 * * * for 5:55 PM daily):");
                        if (cron) scheduleWorkflow(w.workflow_id, cron);
                      }} title="Schedule"
                        className="rounded p-1 text-slate-500 hover:bg-blue-900/30 hover:text-blue-400 ml-auto">
                        <Calendar size={12} />
                      </button>
                    )}
                    {w.cron && (
                      <button onClick={() => {
                        const cron = prompt("Update cron expression:", w.cron);
                        if (cron) scheduleWorkflow(w.workflow_id, cron);
                      }} title="Update schedule"
                        className="rounded p-1 text-jarvis-500 hover:bg-jarvis-900/30 ml-auto">
                        <Calendar size={12} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ===== PATTERNS TAB ===== */}
      {activeTab === "patterns" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-200">Pattern Detection</h2>
            <button onClick={suggestWorkflow}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50">
              <Sparkles size={14} /> Auto-Suggest
            </button>
          </div>

          {stats && (
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "Commands", val: stats.total_commands_recorded, icon: Terminal },
                { label: "Patterns Found", val: stats.patterns_detected, icon: Activity },
                { label: "High Freq (3+)", val: stats.high_frequency_patterns?.length || 0, icon: Zap },
              ].map(({ label, val, icon: Icon }) => (
                <div key={label} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-center">
                  <div className="flex justify-center mb-1"><Icon size={18} className="text-jarvis-400" /></div>
                  <div className="text-xl font-bold text-slate-100">{val}</div>
                  <div className="text-[10px] text-slate-500">{label}</div>
                </div>
              ))}
            </div>
          )}

          {stats && stats.high_frequency_patterns && stats.high_frequency_patterns.length > 0 ? (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-slate-300">High-Frequency Patterns (3+ repetitions)</h3>
              {stats.high_frequency_patterns.map((p, i) => (
                <div key={i} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Activity size={14} className="text-emerald-400" />
                      <span className="text-sm font-medium text-slate-200">
                        {p.command_types?.join(" → ") || "Pattern"} <span className="text-emerald-400">×{p.frequency}</span>
                      </span>
                    </div>
                    <button onClick={async () => {
                      const res = await api("/api/patterns/workflows", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          name: p.command_types?.join(" → ") || "Detected Pattern",
                          commands: p.commands,
                          description: `Auto-detected pattern seen ${p.frequency} times`,
                        }),
                      });
                      if (res.ok) loadAll();
                    }} className="flex items-center gap-1 rounded bg-jarvis-600/30 border border-jarvis-600/40 px-2 py-1 text-[10px] text-jarvis-300 hover:bg-jarvis-600/50">
                      <Sparkles size={10} /> Create Workflow
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {p.commands?.slice(0, 5).map((cmd, ci) => (
                      <span key={ci} className="text-[10px] font-mono text-slate-400 bg-slate-800/50 px-1.5 py-0.5 rounded truncate max-w-[200px]">
                        {cmd}
                      </span>
                    ))}
                    {p.commands?.length > 5 && <span className="text-[10px] text-slate-600">+{p.commands.length - 5} more</span>}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-6 text-center">
              <Activity size={24} className="text-slate-600 mx-auto mb-2" />
              <p className="text-sm text-slate-500">No high-frequency patterns yet.</p>
              <p className="text-xs text-slate-600 mt-1">Patterns appear after repeating commands 3+ times.</p>
            </div>
          )}

          {stats && stats.recent_commands && stats.recent_commands.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Recent Commands</h3>
              <div className="rounded-lg border border-slate-800 divide-y divide-slate-800 max-h-60 overflow-y-auto">
                {[...stats.recent_commands].reverse().map((c, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 text-xs">
                    <div className="flex items-center gap-2 min-w-0">
                      {c.success ? (
                        <CheckCircle size={11} className="text-emerald-600 shrink-0" />
                      ) : (
                        <XCircle size={11} className="text-red-600 shrink-0" />
                      )}
                      <span className="text-slate-400 truncate font-mono">{c.command}</span>
                    </div>
                    <span className="text-slate-600 shrink-0 ml-2">{new Date(c.timestamp).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
