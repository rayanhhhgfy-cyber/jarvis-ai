import { BaseLLMProvider, type LLMMessage, type LLMResponse, type ToolDefinition } from "../types";

export class OllamaProvider extends BaseLLMProvider {
  constructor(config: { baseUrl?: string; model?: string; timeout?: number }) {
    super("ollama", {
      baseUrl: config.baseUrl || "http://localhost:11434",
      model: config.model || "llama3",
      timeout: config.timeout || 120000,
    });
  }

  async generate(
    messages: LLMMessage[],
    _tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const body: Record<string, unknown> = {
      model: this.config.model,
      messages,
      stream: false,
    };
    if (temperature !== undefined) body.temperature = temperature;
    if (maxTokens !== undefined) body.max_tokens = maxTokens;

    const response = await fetch(`${this.config.baseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Ollama error ${response.status}: ${err}`);
    }

    const data = await response.json() as {
      message: { content: string };
      done: boolean;
      total_duration?: number;
      eval_count?: number;
      eval_duration?: number;
    };

    return {
      content: data.message?.content || "",
      usage: data.eval_count ? {
        prompt_tokens: 0,
        completion_tokens: data.eval_count,
        total_tokens: data.eval_count,
      } : undefined,
      model: this.config.model,
      finish_reason: data.done ? "stop" : "unknown",
    };
  }

  async generateStream(
    messages: LLMMessage[],
    onChunk: (chunk: string) => void,
    _tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const body: Record<string, unknown> = {
      model: this.config.model,
      messages,
      stream: true,
    };
    if (temperature !== undefined) body.temperature = temperature;
    if (maxTokens !== undefined) body.max_tokens = maxTokens;

    const response = await fetch(`${this.config.baseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Ollama stream error ${response.status}: ${err}`);
    }

    let fullContent = "";
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split("\n").filter(l => l.trim());
      for (const line of lines) {
        try {
          const event = JSON.parse(line) as { message?: { content?: string }; done?: boolean };
          if (event.message?.content) {
            fullContent += event.message.content;
            onChunk(event.message.content);
          }
        } catch { /* skip */ }
      }
    }

    return { content: fullContent, model: this.config.model, finish_reason: "stop" };
  }

  async isAvailable(): Promise<boolean> {
    try {
      const response = await fetch(`${this.config.baseUrl}/api/tags`, {
        signal: AbortSignal.timeout(3000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}
