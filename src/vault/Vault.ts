import { Database } from "bun:sqlite";
import { existsSync, mkdirSync } from "fs";
import path from "path";
import { createLogger } from "../utils/logger";
import type { ConfigManager } from "../config/ConfigManager";
import type {
  Conversation, Message, Agent, AgentLog, Tool, ToolCall,
  Workflow, WorkflowExecution, Goal, Memory, Sidecar,
  ScheduledTask, Approval, AuditLog, Content, Credential, ConfigEntry
} from "./types";

const log = createLogger("vault");

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT 'direct',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool')),
  content TEXT NOT NULL DEFAULT '',
  tool_calls TEXT NOT NULL DEFAULT '[]',
  tool_results TEXT NOT NULL DEFAULT '[]',
  tokens INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 3,
  status TEXT NOT NULL DEFAULT 'idle' CHECK(status IN ('idle','running','paused','error')),
  parent_id TEXT REFERENCES agents(id),
  config TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_logs (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tools (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  category TEXT NOT NULL,
  required_level INTEGER NOT NULL DEFAULT 1,
  governed INTEGER NOT NULL DEFAULT 0,
  schema TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  tool_name TEXT NOT NULL,
  arguments TEXT NOT NULL DEFAULT '{}',
  result TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','success','error','denied')),
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  steps TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','paused','completed','error')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workflow_executions (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  current_step INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','completed','error','cancelled')),
  input TEXT NOT NULL DEFAULT '{}',
  output TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  key_results TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','cancelled')),
  progress REAL NOT NULL DEFAULT 0.0,
  parent_id TEXT REFERENCES goals(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  value TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'semantic' CHECK(type IN ('semantic','episodic','procedural')),
  importance REAL NOT NULL DEFAULT 0.0,
  tags TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  accessed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sidecars (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  host TEXT NOT NULL,
  port INTEGER NOT NULL,
  fingerprint TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'untrusted' CHECK(status IN ('online','offline','untrusted')),
  capabilities TEXT NOT NULL DEFAULT '[]',
  last_seen TEXT,
  enrolled_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  cron TEXT NOT NULL,
  action TEXT NOT NULL,
  params TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run TEXT,
  next_run TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  requestor TEXT NOT NULL,
  action TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied')),
  channel TEXT NOT NULL DEFAULT 'dashboard',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  action TEXT NOT NULL,
  resource TEXT NOT NULL DEFAULT '',
  details TEXT NOT NULL DEFAULT '{}',
  level TEXT NOT NULL DEFAULT 'info' CHECK(level IN ('info','warn','error','audit')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS content (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('blog','video','social','email')),
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','review','published','archived')),
  platform TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS credentials (
  id TEXT PRIMARY KEY,
  service TEXT NOT NULL,
  username TEXT NOT NULL DEFAULT '',
  encrypted_value TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'general',
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
`;

const INDEXES_SQL = `
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_agent ON agent_logs(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent ON tool_calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow ON workflow_executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_agent ON audit_logs(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
`;

function uid(): string {
  return crypto.randomUUID();
}

type SQLValues = (string | number | null | boolean)[];

export class Vault {
  private db: Database;
  private config: ConfigManager;

  constructor(config: ConfigManager) {
    this.config = config;
    const dbPath = config.get<string>("vault.path") || "./data/vault.db";
    const dir = path.dirname(dbPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    this.db = new Database(dbPath, { create: true });
    this.run("PRAGMA journal_mode = WAL");
    this.run("PRAGMA foreign_keys = ON");
    this.initialize();
    log.info("Vault initialized", { path: dbPath });
  }

  private initialize(): void {
    this.db.exec(SCHEMA_SQL);
    this.db.exec(INDEXES_SQL);
    this.seedTools();
  }

  private seedTools(): void {
    const row = this.db.query("SELECT COUNT(*) as c FROM tools").get() as { c: number };
    if (row.c === 0) {
      const insert = this.db.prepare(
        "INSERT INTO tools (id, name, description, category, required_level, governed) VALUES (?, ?, ?, ?, ?, ?)"
      );
      this.transaction(() => {
        for (const t of TOOLS_SEED) {
          insert.run(uid(), ...t);
        }
      });
    }
  }

  private run(sql: string, ...bindings: (string | number | boolean | null)[]): void {
    (this.db.run as (sql: string, ...args: (string | number | boolean | null)[]) => void)(sql, ...bindings);
  }

  close(): void {
    this.db.close();
    log.info("Vault closed");
  }

  getDb(): Database {
    return this.db;
  }

  // === Conversations ===
  createConversation(title: string, channel = "direct", metadata = "{}"): Conversation {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO conversations (id, title, channel, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
      id, title, channel, now, now, metadata
    );
    return this.getConversation(id)!;
  }

  getConversation(id: string): Conversation | undefined {
    return this.db.query("SELECT * FROM conversations WHERE id = ?").get(id) as Conversation | undefined;
  }

  listConversations(limit = 50, offset = 0): Conversation[] {
    return this.db.query("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?").all(limit, offset) as Conversation[];
  }

  updateConversation(id: string, updates: Partial<Pick<Conversation, "title" | "metadata">>): void {
    const sets: string[] = [];
    const vals: SQLValues = [];
    if (updates.title !== undefined) { sets.push("title = ?"); vals.push(updates.title); }
    if (updates.metadata !== undefined) { sets.push("metadata = ?"); vals.push(updates.metadata); }
    sets.push("updated_at = ?");
    vals.push(new Date().toISOString());
    vals.push(id);
    this.run(`UPDATE conversations SET ${sets.join(", ")} WHERE id = ?`, ...vals);
  }

  deleteConversation(id: string): void {
    this.run("DELETE FROM conversations WHERE id = ?", id);
  }

  // === Messages ===
  addMessage(conversationId: string, role: Message["role"], content: string, toolCalls = "[]", toolResults = "[]", tokens = 0): Message {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO messages (id, conversation_id, role, content, tool_calls, tool_results, tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
      id, conversationId, role, content, toolCalls, toolResults, tokens, now
    );
    this.run("UPDATE conversations SET updated_at = ? WHERE id = ?", now, conversationId);
    return this.db.query("SELECT * FROM messages WHERE id = ?").get(id) as Message;
  }

  getMessages(conversationId: string, limit = 100, offset = 0): Message[] {
    return this.db.query(
      "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?"
    ).all(conversationId, limit, offset) as Message[];
  }

  // === Agents ===
  createAgent(name: string, role: string, level = 3, parentId?: string, config = "{}"): Agent {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO agents (id, name, role, level, status, parent_id, config, created_at, updated_at) VALUES (?, ?, ?, ?, 'idle', ?, ?, ?, ?)",
      id, name, role, level, parentId || null, config, now, now
    );
    return this.getAgent(id)!;
  }

  getAgent(id: string): Agent | undefined {
    return this.db.query("SELECT * FROM agents WHERE id = ?").get(id) as Agent | undefined;
  }

  listAgents(): Agent[] {
    return this.db.query("SELECT * FROM agents ORDER BY created_at DESC").all() as Agent[];
  }

  updateAgent(id: string, updates: Partial<Pick<Agent, "status" | "config" | "level">>): void {
    const sets: string[] = [];
    const vals: (string | number)[] = [];
    if (updates.status !== undefined) { sets.push("status = ?"); vals.push(updates.status); }
    if (updates.config !== undefined) { sets.push("config = ?"); vals.push(updates.config); }
    if (updates.level !== undefined) { sets.push("level = ?"); vals.push(updates.level); }
    sets.push("updated_at = ?");
    vals.push(new Date().toISOString());
    vals.push(id);
    this.run(`UPDATE agents SET ${sets.join(", ")} WHERE id = ?`, ...vals);
  }

  deleteAgent(id: string): void {
    this.run("DELETE FROM agents WHERE id = ?", id);
  }

  // === Agent Logs ===
  addAgentLog(agentId: string, level: string, message: string, data = "{}"): AgentLog {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO agent_logs (id, agent_id, level, message, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
      id, agentId, level, message, data, now
    );
    return this.db.query("SELECT * FROM agent_logs WHERE id = ?").get(id) as AgentLog;
  }

  getAgentLogs(agentId: string, limit = 50): AgentLog[] {
    return this.db.query(
      "SELECT * FROM agent_logs WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?"
    ).all(agentId, limit) as AgentLog[];
  }

  // === Tool Calls ===
  createToolCall(agentId: string, toolName: string, args = "{}"): ToolCall {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO tool_calls (id, agent_id, tool_name, arguments, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
      id, agentId, toolName, args, now
    );
    return this.db.query("SELECT * FROM tool_calls WHERE id = ?").get(id) as ToolCall;
  }

  completeToolCall(id: string, result: string, status: ToolCall["status"], durationMs: number): void {
    const now = new Date().toISOString();
    this.run(
      "UPDATE tool_calls SET result = ?, status = ?, duration_ms = ?, completed_at = ? WHERE id = ?",
      result, status, durationMs, now, id
    );
  }

  // === Workflows ===
  createWorkflow(name: string, steps = "[]", description = ""): Workflow {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO workflows (id, name, description, steps, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?)",
      id, name, description, steps, now, now
    );
    return this.db.query("SELECT * FROM workflows WHERE id = ?").get(id) as Workflow;
  }

  getWorkflow(id: string): Workflow | undefined {
    return this.db.query("SELECT * FROM workflows WHERE id = ?").get(id) as Workflow | undefined;
  }

  listWorkflows(): Workflow[] {
    return this.db.query("SELECT * FROM workflows ORDER BY updated_at DESC").all() as Workflow[];
  }

  // === Goals ===
  createGoal(title: string, keyResults = "[]", description = "", parentId?: string): Goal {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO goals (id, title, description, key_results, status, progress, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', 0.0, ?, ?, ?)",
      id, title, description, keyResults, parentId || null, now, now
    );
    return this.db.query("SELECT * FROM goals WHERE id = ?").get(id) as Goal;
  }

  updateGoalProgress(id: string, progress: number): void {
    const now = new Date().toISOString();
    const status = progress >= 100 ? "completed" : "active";
    this.run("UPDATE goals SET progress = ?, status = ?, updated_at = ? WHERE id = ?", progress, status, now, id);
  }

  listGoals(): Goal[] {
    return this.db.query("SELECT * FROM goals ORDER BY created_at DESC").all() as Goal[];
  }

  // === Memories ===
  setMemory(key: string, value: string, type: Memory["type"] = "semantic", importance = 0.0, tags = "[]"): Memory {
    const now = new Date().toISOString();
    const existing = this.db.query("SELECT * FROM memories WHERE key = ?").get(key) as Memory | undefined;
    if (existing) {
      this.run("UPDATE memories SET value = ?, type = ?, importance = ?, tags = ?, accessed_at = ? WHERE key = ?",
        value, type, importance, tags, now, key);
    } else {
      const id = uid();
      this.run(
        "INSERT INTO memories (id, key, value, type, importance, tags, created_at, accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        id, key, value, type, importance, tags, now, now
      );
    }
    return this.db.query("SELECT * FROM memories WHERE key = ?").get(key) as Memory;
  }

  getMemory(key: string): Memory | undefined {
    return this.db.query("SELECT * FROM memories WHERE key = ?").get(key) as Memory | undefined;
  }

  searchMemories(query: string, limit = 10): Memory[] {
    return this.db.query(
      "SELECT * FROM memories WHERE key LIKE ? OR value LIKE ? OR tags LIKE ? ORDER BY importance DESC LIMIT ?"
    ).all(`%${query}%`, `%${query}%`, `%${query}%`, limit) as Memory[];
  }

  // === Sidecars ===
  enrollSidecar(name: string, host: string, port: number, fingerprint: string, capabilities = "[]"): Sidecar {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO sidecars (id, name, host, port, fingerprint, status, capabilities, enrolled_at) VALUES (?, ?, ?, ?, ?, 'untrusted', ?, ?)",
      id, name, host, port, fingerprint, capabilities, now
    );
    return this.db.query("SELECT * FROM sidecars WHERE id = ?").get(id) as Sidecar;
  }

  getSidecar(id: string): Sidecar | undefined {
    return this.db.query("SELECT * FROM sidecars WHERE id = ?").get(id) as Sidecar | undefined;
  }

  listSidecars(): Sidecar[] {
    return this.db.query("SELECT * FROM sidecars ORDER BY enrolled_at DESC").all() as Sidecar[];
  }

  updateSidecarStatus(id: string, status: Sidecar["status"]): void {
    const now = new Date().toISOString();
    this.run("UPDATE sidecars SET status = ?, last_seen = ? WHERE id = ?", status, now, id);
  }

  // === Scheduled Tasks ===
  createScheduledTask(name: string, cron: string, action: string, params = "{}"): ScheduledTask {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO scheduled_tasks (id, name, cron, action, params, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
      id, name, cron, action, params, now
    );
    return this.db.query("SELECT * FROM scheduled_tasks WHERE id = ?").get(id) as ScheduledTask;
  }

  listScheduledTasks(): ScheduledTask[] {
    return this.db.query("SELECT * FROM scheduled_tasks ORDER BY created_at DESC").all() as ScheduledTask[];
  }

  // === Approvals ===
  createApproval(requestor: string, action: string, details = "{}", channel = "dashboard"): Approval {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO approvals (id, requestor, action, details, status, channel, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
      id, requestor, action, details, channel, now
    );
    return this.db.query("SELECT * FROM approvals WHERE id = ?").get(id) as Approval;
  }

  resolveApproval(id: string, status: "approved" | "denied"): void {
    const now = new Date().toISOString();
    this.run("UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?", status, now, id);
  }

  getPendingApprovals(): Approval[] {
    return this.db.query("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC").all() as Approval[];
  }

  // === Audit Logs ===
  addAuditLog(agentId: string, action: string, level: AuditLog["level"] = "info", resource = "", details = "{}"): AuditLog {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO audit_logs (id, agent_id, action, resource, details, level, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
      id, agentId, action, resource, details, level, now
    );
    return this.db.query("SELECT * FROM audit_logs WHERE id = ?").get(id) as AuditLog;
  }

  getAuditLogs(limit = 100, offset = 0): AuditLog[] {
    return this.db.query("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?").all(limit, offset) as AuditLog[];
  }

  // === Content ===
  createContent(title: string, type: Content["type"], content: string, platform = ""): Content {
    const id = uid();
    const now = new Date().toISOString();
    this.run(
      "INSERT INTO content (id, title, type, content, status, platform, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
      id, title, type, content, platform, now, now
    );
    return this.db.query("SELECT * FROM content WHERE id = ?").get(id) as Content;
  }

  listContentByType(type: Content["type"]): Content[] {
    return this.db.query("SELECT * FROM content WHERE type = ? ORDER BY updated_at DESC").all(type) as Content[];
  }

  // === Config ===
  setConfigValue(key: string, value: string, category = "general"): ConfigEntry {
    const now = new Date().toISOString();
    const existing = this.db.query("SELECT * FROM config WHERE key = ?").get(key) as ConfigEntry | undefined;
    if (existing) {
      this.run("UPDATE config SET value = ?, category = ?, updated_at = ? WHERE key = ?", value, category, now, key);
    } else {
      this.run("INSERT INTO config (key, value, category, updated_at) VALUES (?, ?, ?, ?)", key, value, category, now);
    }
    return this.db.query("SELECT * FROM config WHERE key = ?").get(key) as ConfigEntry;
  }

  getConfigValue(key: string): ConfigEntry | undefined {
    return this.db.query("SELECT * FROM config WHERE key = ?").get(key) as ConfigEntry | undefined;
  }

  // === Transaction support ===
  transaction<T>(fn: () => T): T {
    return this.db.transaction(fn)();
  }
}

const TOOLS_SEED: Array<[string, string, string, number, number]> = [
  ["run_command", "Execute shell commands", "terminal", 2, 1],
  ["read_file", "Read file contents", "filesystem", 1, 0],
  ["write_file", "Write content to a file", "filesystem", 2, 0],
  ["list_directory", "List files in a directory", "filesystem", 1, 0],
  ["browser_navigate", "Navigate browser to a URL", "browser", 2, 0],
  ["browser_click", "Click an element on the page", "browser", 2, 0],
  ["browser_type", "Type text into an input", "browser", 2, 0],
  ["browser_scroll", "Scroll the browser page", "browser", 1, 0],
  ["browser_snapshot", "Get page HTML snapshot", "browser", 1, 0],
  ["browser_screenshot", "Take browser screenshot", "browser", 1, 0],
  ["browser_evaluate", "Run JavaScript in browser", "browser", 3, 1],
  ["browser_upload_file", "Upload file through browser", "browser", 2, 0],
  ["get_clipboard", "Get clipboard contents", "system", 1, 0],
  ["set_clipboard", "Set clipboard contents", "system", 1, 0],
  ["capture_screen", "Capture screen screenshot", "system", 1, 0],
  ["get_system_info", "Get system information", "system", 1, 0],
  ["delegate_task", "Delegate task to sub-agent", "delegation", 3, 0],
  ["manage_agents", "Manage persistent async agents", "agents", 3, 1],
  ["content_pipeline", "Generate blog/video/social posts", "content", 2, 0],
  ["manage_goals", "Manage OKR goals", "goals", 2, 0],
  ["manage_workflow", "Manage workflow execution", "workflows", 3, 1],
  ["desktop_type", "Type text into application window", "desktop", 2, 0],
  ["desktop_click", "Click at screen coordinates", "desktop", 2, 0],
  ["desktop_screenshot", "Capture application window", "desktop", 1, 0],
];
