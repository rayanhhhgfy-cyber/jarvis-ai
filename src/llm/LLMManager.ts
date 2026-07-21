import { createLogger } from "../utils/logger";
import type { ConfigManager } from "../config/ConfigManager";
import { AnthropicProvider } from "./providers/AnthropicProvider";
import { OpenAIProvider } from "./providers/OpenAIProvider";
import { GroqProvider } from "./providers/GroqProvider";
import { GeminiProvider } from "./providers/GeminiProvider";
import { OpenRouterProvider } from "./providers/OpenRouterProvider";
import { NVIDIAProvider } from "./providers/NVIDIAProvider";
import { OllamaProvider } from "./providers/OllamaProvider";
import { OpenAICompatibleProvider } from "./providers/OpenAICompatibleProvider";
import { LiteLLMProvider } from "./providers/LiteLLMProvider";
import { BaseLLMProvider, type LLMMessage, type LLMResponse, type ToolDefinition } from "./types";

const log = createLogger("llm-manager");

type ProviderConstructor = new (...args: never[]) => BaseLLMProvider;

export class LLMManager {
  private providers: Map<string, BaseLLMProvider> = new Map();
  private primaryName: string;
  private fallbackOrder: string[];
  private maxRetries: number;
  private timeout: number;
  private temperature: number;
  private maxTokens: number;
  private config: ConfigManager;

  constructor(config: ConfigManager) {
    this.config = config;
    this.primaryName = config.get<string>("llm.primary") || "anthropic";
    this.fallbackOrder = config.get<string[]>("llm.fallbacks") || [];
    this.maxRetries = config.get<number>("llm.maxRetries") || 3;
    this.timeout = config.get<number>("llm.timeout") || 90000;
    this.temperature = config.get<number>("llm.temperature") || 0.7;
    this.maxTokens = config.get<number>("llm.maxTokens") || 4096;

    this.providers = this.initializeProviders();
    log.info(`LLMManager initialized. Primary: ${this.primaryName}, Fallbacks: ${this.fallbackOrder.join(", ")}`);
  }

  private initializeProviders(): Map<string, BaseLLMProvider> {
    const map = new Map<string, BaseLLMProvider>();
    const p = this.config.get<Record<string, Record<string, unknown>>>("providers") || {};

    if (p.anthropic?.apiKey) {
      map.set("anthropic", new AnthropicProvider({
        apiKey: p.anthropic.apiKey as string,
        model: p.anthropic.model as string || "claude-sonnet-4-20250514",
        timeout: this.timeout,
      }));
    }
    if (p.openai?.apiKey) {
      map.set("openai", new OpenAIProvider({
        apiKey: p.openai.apiKey as string,
        model: p.openai.model as string || "gpt-4o",
        timeout: this.timeout,
      }));
    }
    if (p.groq?.apiKey) {
      map.set("groq", new GroqProvider({
        apiKey: p.groq.apiKey as string,
        model: p.groq.model as string || "llama-3.3-70b-versatile",
        timeout: this.timeout,
      }));
    }
    if (p.gemini?.apiKey) {
      map.set("gemini", new GeminiProvider({
        apiKey: p.gemini.apiKey as string,
        model: p.gemini.model as string || "gemini-2.0-flash",
        timeout: this.timeout,
      }));
    }
    if (p.openrouter?.apiKey) {
      map.set("openrouter", new OpenRouterProvider({
        apiKey: p.openrouter.apiKey as string,
        model: (p.openrouter.model as string) || "anthropic/claude-sonnet-4",
        timeout: this.timeout,
      }));
    }
    map.set("nvidia", new NVIDIAProvider({
      model: p.nvidia?.model as string || "meta/llama-3.3-70b-instruct",
      timeout: this.timeout,
    }));
    map.set("ollama", new OllamaProvider({
      baseUrl: (p.ollama?.baseUrl as string) || "http://localhost:11434",
      model: (p.ollama?.model as string) || "llama3",
      timeout: this.timeout,
    }));
    if (p.openaiCompatible?.baseUrl) {
      map.set("openai-compatible", new OpenAICompatibleProvider({
        baseUrl: p.openaiCompatible.baseUrl as string,
        apiKey: p.openaiCompatible.apiKey as string,
        model: p.openaiCompatible.model as string || "default",
        timeout: this.timeout,
      }));
    }
    if (p.litellm?.baseUrl) {
      map.set("litellm", new LiteLLMProvider({
        baseUrl: p.litellm.baseUrl as string,
        apiKey: p.litellm.apiKey as string,
        model: p.litellm.model as string || "gpt-3.5-turbo",
        timeout: this.timeout,
      }));
    }

    return map;
  }

  getProvider(name: string): BaseLLMProvider | undefined {
    return this.providers.get(name);
  }

  getAvailableProviders(): string[] {
    return Array.from(this.providers.keys());
  }

  async generate(
    messages: LLMMessage[],
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const chain = this.buildChain();
    let lastError: Error | null = null;

    for (const providerName of chain) {
      const provider = this.providers.get(providerName);
      if (!provider) continue;

      for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
        try {
          log.info(`Attempt ${attempt}/${this.maxRetries} with ${providerName} (${provider.getModel()})`);
          const result = await provider.generate(messages, tools, temperature ?? this.temperature, maxTokens ?? this.maxTokens);
          log.info(`Success with ${providerName}`, { model: result.model, finish_reason: result.finish_reason });
          return result;
        } catch (err) {
          lastError = err as Error;
          log.warn(`Provider ${providerName} attempt ${attempt} failed`, { error: lastError.message });
          if (attempt < this.maxRetries) {
            const delay = Math.min(1000 * Math.pow(2, attempt - 1), 10000);
            await new Promise(r => setTimeout(r, delay));
          }
        }
      }
      log.warn(`Provider ${providerName} exhausted all retries, trying next`);
    }

    throw new Error(`All LLM providers failed. Last error: ${lastError?.message}`);
  }

  async generateStream(
    messages: LLMMessage[],
    onChunk: (chunk: string) => void,
    tools?: ToolDefinition[],
    temperature?: number,
    maxTokens?: number
  ): Promise<LLMResponse> {
    const chain = this.buildChain();
    let lastError: Error | null = null;

    for (const providerName of chain) {
      const provider = this.providers.get(providerName);
      if (!provider) continue;

      try {
        log.info(`Streaming with ${providerName} (${provider.getModel()})`);
        return await provider.generateStream(
          messages, onChunk, tools, temperature ?? this.temperature, maxTokens ?? this.maxTokens
        );
      } catch (err) {
        lastError = err as Error;
        log.warn(`Provider ${providerName} stream failed`, { error: lastError.message });
      }
    }

    throw new Error(`All LLM providers failed for streaming. Last error: ${lastError?.message}`);
  }

  async checkAvailability(): Promise<Record<string, boolean>> {
    const results: Record<string, boolean> = {};
    for (const [name, provider] of this.providers) {
      try {
        results[name] = await provider.isAvailable();
      } catch {
        results[name] = false;
      }
    }
    return results;
  }

  private buildChain(): string[] {
    const chain: string[] = [];
    if (this.providers.has(this.primaryName)) {
      chain.push(this.primaryName);
    }
    for (const fallback of this.fallbackOrder) {
      if (fallback !== this.primaryName && this.providers.has(fallback)) {
        chain.push(fallback);
      }
    }
    return chain;
  }
}
