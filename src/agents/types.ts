export interface AgentRole {
  name: string;
  description: string;
  systemPrompt: string;
  model: string;
  temperature: number;
  maxTokens: number;
  maxIterations: number;
  tools: string[];
  subAgents: string[];
  allowedLevel: number;
  safety: {
    requireApproval: string[];
    denyTools: string[];
    maxConcurrency: number;
  };
}

export interface AgentState {
  id: string;
  role: AgentRole;
  conversationId: string;
  messages: import("../llm/types").LLMMessage[];
  iteration: number;
  parentId: string | null;
  status: "idle" | "thinking" | "executing" | "awaiting_approval" | "done" | "error";
}

export interface SubAgentInfo {
  id: string;
  name: string;
  role: string;
  status: string;
  task: string;
  result?: string;
  error?: string;
}
