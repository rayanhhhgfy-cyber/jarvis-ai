export interface Conversation {
  id: string;
  title: string;
  channel: string;
  created_at: string;
  updated_at: string;
  metadata: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  tool_calls: string;
  tool_results: string;
  tokens: number;
  created_at: string;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  level: number;
  status: "idle" | "running" | "paused" | "error";
  parent_id: string | null;
  config: string;
  created_at: string;
  updated_at: string;
}

export interface AgentLog {
  id: string;
  agent_id: string;
  level: string;
  message: string;
  data: string;
  created_at: string;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  category: string;
  required_level: number;
  governed: boolean;
  schema: string;
  enabled: boolean;
}

export interface ToolCall {
  id: string;
  agent_id: string;
  tool_name: string;
  arguments: string;
  result: string;
  status: "pending" | "running" | "success" | "error" | "denied";
  duration_ms: number;
  created_at: string;
  completed_at: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  steps: string;
  status: "draft" | "active" | "paused" | "completed" | "error";
  created_at: string;
  updated_at: string;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  current_step: number;
  status: "running" | "completed" | "error" | "cancelled";
  input: string;
  output: string;
  started_at: string;
  completed_at: string;
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  key_results: string;
  status: "active" | "completed" | "cancelled";
  progress: number;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Memory {
  id: string;
  key: string;
  value: string;
  type: "semantic" | "episodic" | "procedural";
  importance: number;
  tags: string;
  created_at: string;
  accessed_at: string;
}

export interface Sidecar {
  id: string;
  name: string;
  host: string;
  port: number;
  fingerprint: string;
  status: "online" | "offline" | "untrusted";
  capabilities: string;
  last_seen: string;
  enrolled_at: string;
}

export interface ScheduledTask {
  id: string;
  name: string;
  cron: string;
  action: string;
  params: string;
  enabled: boolean;
  last_run: string;
  next_run: string;
  created_at: string;
}

export interface Approval {
  id: string;
  requestor: string;
  action: string;
  details: string;
  status: "pending" | "approved" | "denied";
  channel: string;
  created_at: string;
  resolved_at: string;
}

export interface AuditLog {
  id: string;
  agent_id: string;
  action: string;
  resource: string;
  details: string;
  level: "info" | "warn" | "error" | "audit";
  created_at: string;
}

export interface Content {
  id: string;
  title: string;
  type: "blog" | "video" | "social" | "email";
  content: string;
  status: "draft" | "review" | "published" | "archived";
  platform: string;
  created_at: string;
  updated_at: string;
}

export interface Credential {
  id: string;
  service: string;
  username: string;
  encrypted_value: string;
  expires_at: string;
  created_at: string;
  updated_at: string;
}

export interface ConfigEntry {
  key: string;
  value: string;
  category: string;
  updated_at: string;
}
