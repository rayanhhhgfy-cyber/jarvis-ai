import { BaseLLMProvider, type LLMMessage, type LLMResponse, type ToolDefinition } from "../types";

export class OpenAIProvider extends BaseLLMProvider {
  constructor(config: { apiKey: string; model: string; baseUrl?: string; timeout?: number }) {
    super("openai", {
      apiKey: config.apiKey,
      model: config.model,
      baseUrl: config.baseUrl || "https://api.openai.com/v1",
      timeout: config.timeout || 90000,
    });
  }

  async generate(
    messages: LLMMessage[],
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const body: Record<string, unknown> = {
      model: this.config.model,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
        ...(m.name ? { name: m.name } : {}),
        ...(m.tool_call_id ? { tool_call_id: m.tool_call_id } : {}),
        ...(m.tool_calls ? { tool_calls: m.tool_calls } : {}),
      })),
    };

    if (temperature !== undefined) body.temperature = temperature;
    if (maxTokens !== undefined) body.max_tokens = maxTokens;
    if (tools && tools.length > 0) body.tools = tools;

    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`OpenAI API error ${response.status}: ${err}`);
    }

    const data = await response.json() as {
      choices: Array<{
        message: {
          content: string | null;
          tool_calls?: Array<{
            id: string;
            type: "function";
            function: { name: string; arguments: string };
          }>;
        };
        finish_reason: string;
      }>;
      usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
      model: string;
    };

    return {
      content: data.choices[0]?.message?.content || "",
      tool_calls: data.choices[0]?.message?.tool_calls,
      usage: data.usage,
      model: data.model,
      finish_reason: data.choices[0]?.finish_reason || "stop",
    };
  }

  async generateStream(
    messages: LLMMessage[],
    onChunk: (chunk: string) => void,
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const body: Record<string, unknown> = {
      model: this.config.model,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
      })),
      stream: true,
    };

    if (temperature !== undefined) body.temperature = temperature;
    if (maxTokens !== undefined) body.max_tokens = maxTokens;
    if (tools && tools.length > 0) body.tools = tools;

    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`OpenAI stream error ${response.status}: ${err}`);
    }

    let fullContent = "";
    let toolCalls: LLMResponse["tool_calls"];
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
          const event = JSON.parse(jsonStr) as {
            choices: Array<{
              delta: { content?: string; tool_calls?: Array<Record<string, unknown>> };
              finish_reason?: string;
            }>;
          };
          const delta = event.choices?.[0]?.delta;
          if (delta?.content) {
            fullContent += delta.content;
            onChunk(delta.content);
          }
          if (delta?.tool_calls) {
            toolCalls = delta.tool_calls as unknown as LLMResponse["tool_calls"];
          }
        } catch { /* skip parse errors */ }
      }
    }

    return {
      content: fullContent,
      tool_calls: toolCalls,
      model: this.config.model,
      finish_reason: "stop",
    };
  }

  async isAvailable(): Promise<boolean> {
    try {
      const response = await fetch("https://api.openai.com/v1/models", {
        headers: { Authorization: `Bearer ${this.config.apiKey}` },
        signal: AbortSignal.timeout(5000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}
