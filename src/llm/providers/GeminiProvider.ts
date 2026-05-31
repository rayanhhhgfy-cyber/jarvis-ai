import { BaseLLMProvider, type LLMMessage, type LLMResponse, type ToolDefinition } from "../types";

export class GeminiProvider extends BaseLLMProvider {
  constructor(config: { apiKey: string; model: string; timeout?: number }) {
    super("gemini", {
      apiKey: config.apiKey,
      model: config.model,
      baseUrl: "https://generativelanguage.googleapis.com/v1beta",
      timeout: config.timeout || 90000,
    });
  }

  async generate(
    messages: LLMMessage[],
    _tools?: ToolDefinition[],
    temperature?: number,
    _maxTokens?: number
  ): Promise<LLMResponse> {
    const contents = messages
      .filter(m => m.role !== "system")
      .map(m => ({
        role: m.role === "assistant" ? "model" : m.role,
        parts: [{ text: m.content }],
      }));

    const systemInstruction = messages.find(m => m.role === "system");

    const body: Record<string, unknown> = {
      contents,
      generationConfig: {
        ...(temperature !== undefined ? { temperature } : {}),
      },
    };
    if (systemInstruction) {
      body.systemInstruction = { parts: [{ text: systemInstruction.content }] };
    }

    const response = await fetch(
      `${this.config.baseUrl}/models/${this.config.model}:generateContent?key=${this.config.apiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(this.config.timeout!),
      }
    );

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Gemini API error ${response.status}: ${err}`);
    }

    const data = await response.json() as {
      candidates: Array<{
        content: { parts: Array<{ text: string }> };
        finishReason: string;
        usageMetadata?: { promptTokenCount: number; candidatesTokenCount: number; totalTokenCount: number };
      }>;
    };

    const candidate = data.candidates?.[0];
    const text = candidate?.content?.parts?.map((p: { text: string }) => p.text).join("") || "";

    return {
      content: text,
      usage: candidate?.usageMetadata ? {
        prompt_tokens: candidate.usageMetadata.promptTokenCount,
        completion_tokens: candidate.usageMetadata.candidatesTokenCount,
        total_tokens: candidate.usageMetadata.totalTokenCount,
      } : undefined,
      model: this.config.model,
      finish_reason: candidate?.finishReason || "stop",
    };
  }

  async generateStream(
    messages: LLMMessage[],
    onChunk: (chunk: string) => void,
    _tools?: ToolDefinition[],
    temperature?: number,
    _maxTokens?: number
  ): Promise<LLMResponse> {
    const contents = messages
      .filter(m => m.role !== "system")
      .map(m => ({
        role: m.role === "assistant" ? "model" : m.role,
        parts: [{ text: m.content }],
      }));

    const body: Record<string, unknown> = {
      contents,
      generationConfig: { ...(temperature !== undefined ? { temperature } : {}) },
    };

    const response = await fetch(
      `${this.config.baseUrl}/models/${this.config.model}:streamGenerateContent?alt=sse&key=${this.config.apiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(this.config.timeout!),
      }
    );

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Gemini stream error ${response.status}: ${err}`);
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
        if (!jsonStr) continue;
        try {
          const event = JSON.parse(jsonStr) as {
            candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
          };
          const text = event.candidates?.[0]?.content?.parts?.[0]?.text;
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
    try {
      const response = await fetch(
        `${this.config.baseUrl}/models?key=${this.config.apiKey}`,
        { signal: AbortSignal.timeout(5000) }
      );
      return response.ok;
    } catch {
      return false;
    }
  }
}
