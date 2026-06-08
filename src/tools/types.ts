export interface ToolContext {
  agentId: string;
  agentLevel: number;
  configManager: import("../config/ConfigManager").ConfigManager;
  vault: import("../vault/Vault").Vault;
  llmManager: import("../llm/LLMManager").LLMManager;
  onApproval?: (action: string, details: Record<string, unknown>) => Promise<boolean>;
}

export interface ToolResult {
  success: boolean;
  data?: unknown;
  error?: string;
  output?: string;
}

export interface ToolDefinition {
  name: string;
  description: string;
  category: string;
  requiredLevel: number;
  governed: boolean;
  parameters: Record<string, unknown>;
  execute: (args: Record<string, unknown>, ctx: ToolContext) => Promise<ToolResult>;
}

export type ToolHandler = (args: Record<string, unknown>, ctx: ToolContext) => Promise<ToolResult>;
