export interface LLMConfig {
  primary: string;
  fallbacks: string[];
  maxRetries: number;
  timeout: number;
  temperature: number;
  maxTokens: number;
}

export interface ProviderConfig {
  apiKey?: string;
  baseUrl?: string;
  model: string;
  maxRetries?: number;
  timeout?: number;
  options?: Record<string, unknown>;
}

export interface AnthropicConfig extends ProviderConfig {
  apiKey: string;
  model: "claude-sonnet-4-20250514" | "claude-haiku-3-5-20241022" | "claude-opus-4-20250514";
}

export interface OpenAIConfig extends ProviderConfig {
  apiKey: string;
  model: "gpt-4o" | "gpt-4" | "o1" | "o3";
}

export interface GroqConfig extends ProviderConfig {
  apiKey: string;
  model: "llama-3.3-70b-versatile" | "mixtral-8x7b-32768";
}

export interface GeminiConfig extends ProviderConfig {
  apiKey: string;
  model: "gemini-2.0-flash" | "gemini-2.0-pro";
}

export interface OpenRouterConfig extends ProviderConfig {
  apiKey: string;
  model: string;
}

export interface NVIDIAConfig extends ProviderConfig {
  model: string;
}

export interface OllamaConfig extends ProviderConfig {
  baseUrl: string;
  model: string;
}

export interface OpenAICompatibleConfig extends ProviderConfig {
  baseUrl: string;
  apiKey?: string;
  model: string;
}

export interface LiteLLMConfig extends ProviderConfig {
  baseUrl: string;
  apiKey?: string;
  model: string;
}

export interface AgentConfig {
  maxIterations: number;
  defaultLevel: number;
  rolePath: string;
  allowSubAgents: boolean;
}

export interface SafetyConfig {
  noLocalTools: boolean;
  defaultAuthorityLevel: number;
  governedCategories: string[];
  approvalRequired: boolean;
  commandTimeout: number;
  outputTruncationSize: number;
  maxFileReadSize: number;
  emergencyPause: boolean;
}

export interface VaultConfig {
  path: string;
  backupInterval: number;
}

export interface WebSocketConfig {
  port: number;
  host: string;
  maxConnections: number;
  heartbeatInterval: number;
}

export interface ObserverConfig {
  fileWatcher: boolean;
  clipboard: boolean;
  processes: boolean;
  notifications: boolean;
  email: boolean;
  calendar: boolean;
}

export interface ChannelConfig {
  telegram?: { token: string; enabled: boolean };
  discord?: { token: string; enabled: boolean };
  whatsapp?: { phoneNumberId: string; token: string; enabled: boolean };
  signal?: { phoneNumber: string; enabled: boolean };
}

export interface SidecarConfig {
  enabled: boolean;
  port: number;
  binaryValidation: boolean;
  maxJsonSize: number;
  maxBinarySize: number;
}

export interface SiteBuilderConfig {
  enabled: boolean;
  defaultTemplate: string;
  outputDir: string;
}

export interface Config {
  name: string;
  version: string;
  dataDir: string;
  llm: LLMConfig;
  providers: {
    anthropic?: AnthropicConfig;
    openai?: OpenAIConfig;
    groq?: GroqConfig;
    gemini?: GeminiConfig;
    openrouter?: OpenRouterConfig;
    nvidia?: NVIDIAConfig;
    ollama?: OllamaConfig;
    openaiCompatible?: OpenAICompatibleConfig;
    litellm?: LiteLLMConfig;
  };
  agent: AgentConfig;
  safety: SafetyConfig;
  vault: VaultConfig;
  websocket: WebSocketConfig;
  observers: ObserverConfig;
  channels: ChannelConfig;
  sidecar: SidecarConfig;
  siteBuilder: SiteBuilderConfig;
}

export const DEFAULT_CONFIG: Config = {
  name: "jarvis-omega",
  version: "1.0.0",
  dataDir: process.env.DATA_DIR || "./data",
  llm: {
    primary: "anthropic",
    fallbacks: ["openai", "groq", "gemini", "openrouter"],
    maxRetries: 3,
    timeout: 90000,
    temperature: 0.7,
    maxTokens: 4096,
  },
  providers: {},
  agent: {
    maxIterations: 200,
    defaultLevel: 3,
    rolePath: "./roles/personal-assistant.yaml",
    allowSubAgents: true,
  },
  safety: {
    noLocalTools: false,
    defaultAuthorityLevel: 3,
    governedCategories: ["filesystem_delete", "system_shutdown", "network_modify"],
    approvalRequired: true,
    commandTimeout: 30000,
    outputTruncationSize: 10240,
    maxFileReadSize: 102400,
    emergencyPause: false,
  },
  vault: {
    path: "./data/vault.db",
    backupInterval: 3600000,
  },
  websocket: {
    port: 3142,
    host: "0.0.0.0",
    maxConnections: 100,
    heartbeatInterval: 30000,
  },
  observers: {
    fileWatcher: false,
    clipboard: false,
    processes: false,
    notifications: false,
    email: false,
    calendar: false,
  },
  channels: {
    telegram: { token: "", enabled: false },
    discord: { token: "", enabled: false },
    whatsapp: { phoneNumberId: "", token: "", enabled: false },
    signal: { phoneNumber: "", enabled: false },
  },
  sidecar: {
    enabled: false,
    port: 3143,
    binaryValidation: true,
    maxJsonSize: 1048576,
    maxBinarySize: 52428800,
  },
  siteBuilder: {
    enabled: false,
    defaultTemplate: "nextjs",
    outputDir: "./sites",
  },
};
