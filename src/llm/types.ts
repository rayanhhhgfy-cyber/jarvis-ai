export interface LLMMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
}

export interface ToolDefinition {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface LLMResponse {
  content: string | null;
  tool_calls?: ToolCall[];
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  model: string;
  finish_reason: string;
}

export interface LLMProviderConfig {
  apiKey?: string;
  baseUrl?: string;
  model: string;
  maxRetries?: number;
  timeout?: number;
  options?: Record<string, unknown>;
}

export abstract class BaseLLMProvider {
  protected config: LLMProviderConfig;
  protected name: string;

  constructor(name: string, config: LLMProviderConfig) {
    this.name = name;
    this.config = config;
  }

  getName(): string {
    return this.name;
  }

  getModel(): string {
    return this.config.model;
  }

  abstract generate(
    messages: LLMMessage[],
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse>;

  abstract generateStream(
    messages: LLMMessage[],
    onChunk: (chunk: string) => void,
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse>;

  abstract isAvailable(): Promise<boolean>;
}
