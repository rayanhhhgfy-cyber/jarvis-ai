import { BaseLLMProvider, type LLMMessage, type LLMResponse, type ToolDefinition } from "../types";

export class AnthropicProvider extends BaseLLMProvider {
  constructor(config: { apiKey: string; model: string; baseUrl?: string; timeout?: number }) {
    super("anthropic", {
      apiKey: config.apiKey,
      model: config.model,
      baseUrl: config.baseUrl || "https://api.anthropic.com/v1",
      timeout: config.timeout || 90000,
    });
  }

  async generate(
    messages: LLMMessage[],
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const systemMessages = messages.filter(m => m.role === "system").map(m => m.content);
    const nonSystemMessages = messages.filter(m => m.role !== "system");

    const body: Record<string, unknown> = {
      model: this.config.model,
      max_tokens: maxTokens || 4096,
      messages: nonSystemMessages.map(m => ({
        role: m.role === "tool" ? "user" : m.role,
        content: m.content,
      })),
    };

    if (systemMessages.length > 0) {
      body.system = systemMessages;
    }
    if (temperature !== undefined) body.temperature = temperature;
    if (tools && tools.length > 0) {
      body.tools = tools.map(t => t.function);
    }

    const response = await fetch(`${this.config.baseUrl}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": this.config.apiKey!,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Anthropic API error ${response.status}: ${err}`);
    }

    const data = await response.json() as {
      content: Array<{ type: string; text?: string; id?: string; name?: string; input?: Record<string, unknown> }>;
      usage: { input_tokens: number; output_tokens: number };
      stop_reason: string;
    };

    let content = "";
    const toolCalls = [];
    for (const block of data.content) {
      if (block.type === "text") content += block.text || "";
      if (block.type === "tool_use") {
        toolCalls.push({
          id: block.id || crypto.randomUUID(),
          type: "function" as const,
          function: {
            name: block.name || "unknown",
            arguments: JSON.stringify(block.input || {}),
          },
        });
      }
    }

    return {
      content,
      tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
      usage: {
        prompt_tokens: data.usage.input_tokens,
        completion_tokens: data.usage.output_tokens,
        total_tokens: data.usage.input_tokens + data.usage.output_tokens,
      },
      model: this.config.model,
      finish_reason: data.stop_reason,
    };
  }

  async generateStream(
    messages: LLMMessage[],
    onChunk: (chunk: string) => void,
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const systemMessages = messages.filter(m => m.role === "system").map(m => m.content);
    const nonSystemMessages = messages.filter(m => m.role !== "system");

    const body: Record<string, unknown> = {
      model: this.config.model,
      max_tokens: maxTokens || 4096,
      messages: nonSystemMessages.map(m => ({
        role: m.role === "tool" ? "user" : m.role,
        content: m.content,
      })),
      stream: true,
    };

    if (systemMessages.length > 0) body.system = systemMessages;
    if (temperature !== undefined) body.temperature = temperature;
    if (tools && tools.length > 0) body.tools = tools.map(t => t.function);

    const response = await fetch(`${this.config.baseUrl}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": this.config.apiKey!,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Anthropic stream error ${response.status}: ${err}`);
    }

    let fullContent = "";
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split("\n").filter(l => l.startsWith("data: "));
      for (const line of lines) {
        const jsonStr = line.slice(6).trim();
        if (jsonStr === "[DONE]" || !jsonStr) continue;
        try {
          const event = JSON.parse(jsonStr) as { type: string; delta?: { text?: string }; content_block?: { type: string; text?: string } };
          if (event.type === "content_block_delta" && event.delta?.text) {
            fullContent += event.delta.text;
            onChunk(event.delta.text);
          }
        } catch { /* skip parse errors */ }
      }
    }

    return {
      content: fullContent,
      model: this.config.model,
      finish_reason: "stop",
    };
  }

  async isAvailable(): Promise<boolean> {
    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": this.config.apiKey!,
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify({ model: this.config.model, max_tokens: 1, messages: [{ role: "user", content: "ping" }] }),
        signal: AbortSignal.timeout(5000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}
