import { BaseLLMProvider, type LLMMessage, type LLMResponse, type ToolDefinition } from "../types";

export class NVIDIAProvider extends BaseLLMProvider {
  constructor(config: { model?: string; timeout?: number }) {
    super("nvidia", {
      model: config.model || "meta/llama-3.3-70b-instruct",
      baseUrl: "https://integrate.api.nvidia.com/v1",
      timeout: config.timeout || 90000,
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
    };
    if (temperature !== undefined) body.temperature = temperature;
    if (maxTokens !== undefined) body.max_tokens = maxTokens;

    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(this.config.apiKey ? { Authorization: `Bearer ${this.config.apiKey}` } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`NVIDIA error ${response.status}: ${err}`);
    }

    const data = await response.json() as {
      choices: Array<{ message: { content: string }; finish_reason: string }>;
      usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
      model: string;
    };

    return {
      content: data.choices[0]?.message?.content || "",
      usage: data.usage,
      model: data.model,
      finish_reason: data.choices[0]?.finish_reason || "stop",
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

    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(this.config.apiKey ? { Authorization: `Bearer ${this.config.apiKey}` } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeout!),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`NVIDIA stream error ${response.status}: ${err}`);
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
          const event = JSON.parse(jsonStr) as {
            choices: Array<{ delta: { content?: string }; finish_reason?: string }>;
          };
          const text = event.choices?.[0]?.delta?.content;
          if (text) {
            fullContent += text;
            onChunk(text);
          }
        } catch { /* skip */ }
      }
    }

    return { content: fullContent, model: this.config.model, finish_reason: "stop" };
  }

  async isAvailable(): Promise<boolean> {
    return true;
  }
}
