import { createLogger } from "../utils/logger";
import { ConfigManager } from "../config/ConfigManager";
import { Vault } from "../vault/Vault";
import { LLMManager } from "../llm/LLMManager";
import { ToolRegistry } from "../tools/index";
import { AgentOrchestrator } from "../agents/AgentOrchestrator";
import { SafetyManager } from "../safety/SafetyManager";
import { AuthorityGate } from "../safety/AuthorityGate";
import { ServiceRegistry } from "./ServiceRegistry";
import { HeartbeatService } from "./services/HeartbeatService";
import { AgentService } from "./services/AgentService";
import { WebSocketService } from "./services/WebSocketService";
import { ObserverService } from "./services/ObserverService";
import { ChannelService } from "./services/ChannelService";
import { SidecarService } from "./services/SidecarService";
import { SiteBuilderService } from "./services/SiteBuilderService";

const log = createLogger("daemon");

export interface DaemonOptions {
  configPath?: string;
  noLocalTools?: boolean;
}

export class Daemon {
  private configManager: ConfigManager;
  private vault: Vault;
  private llmManager: LLMManager;
  private toolRegistry: ToolRegistry;
  private agentOrchestrator: AgentOrchestrator;
  private safetyManager: SafetyManager;
  private authorityGate: AuthorityGate;
  private serviceRegistry: ServiceRegistry;
  private running = false;

  constructor(options: DaemonOptions = {}) {
    log.info("Initializing Jarvis Omega daemon...");

    this.configManager = new ConfigManager(options.configPath);

    if (options.noLocalTools) {
      this.configManager.set("safety.noLocalTools", true);
    }

    this.vault = new Vault(this.configManager);
    this.llmManager = new LLMManager(this.configManager);
    this.toolRegistry = new ToolRegistry();
    this.agentOrchestrator = new AgentOrchestrator(
      this.llmManager, this.toolRegistry, this.vault, this.configManager,
    );
    this.safetyManager = new SafetyManager(this.configManager);
    this.authorityGate = new AuthorityGate(this.configManager);
    this.serviceRegistry = new ServiceRegistry();

    log.info("Daemon components initialized");
  }

  async start(): Promise<void> {
    if (this.running) {
      log.warn("Daemon already running");
      return;
    }

    log.info("Starting Jarvis Omega daemon...");

    // Register services in order
    const heartbeat = new HeartbeatService();
    const agentService = new AgentService(this.agentOrchestrator);
    const wsService = new WebSocketService(this.configManager, this.agentOrchestrator);
    const observerService = new ObserverService();
    const channelService = new ChannelService();
    const sidecarService = new SidecarService(this.vault);
    const siteBuilderService = new SiteBuilderService();

    // Expose agent service for WS to get agent ID
    (globalThis as Record<string, unknown>).__agentService = agentService;

    this.serviceRegistry.register(heartbeat);
    this.serviceRegistry.register(agentService);
    this.serviceRegistry.register(wsService);
    this.serviceRegistry.register(observerService);
    this.serviceRegistry.register(channelService);
    this.serviceRegistry.register(sidecarService);
    this.serviceRegistry.register(siteBuilderService);

    // Start all services
    await this.serviceRegistry.startAll();

    // Update WS with agent ID after agent is initialized
    const agentId = agentService.getAgentId();
    if (agentId) {
      wsService.setAgentId(agentId);
    }

    this.running = true;
    log.info("Jarvis Omega daemon fully operational");

    // Print startup banner
    console.log(`
╔══════════════════════════════════════╗
║        JARVIS OMEGA DAEMON          ║
║  Always-on Autonomous AI Assistant  ║
║                                      ║
║  WebSocket: :${this.configManager.get<number>("websocket.port") || 3142}    ║
║  Agent: ${agentId ? "Active" : "Initializing..."}                   ║
╚══════════════════════════════════════╝
    `);
  }

  async stop(): Promise<void> {
    if (!this.running) return;
    log.info("Shutting down Jarvis Omega daemon...");
    await this.serviceRegistry.stopAll();
    this.vault.close();
    this.running = false;
    log.info("Daemon shut down complete");
  }

  getServiceRegistry(): ServiceRegistry {
    return this.serviceRegistry;
  }

  getConfigManager(): ConfigManager {
    return this.configManager;
  }

  getVault(): Vault {
    return this.vault;
  }

  getLLMManager(): LLMManager {
    return this.llmManager;
  }

  getAgentOrchestrator(): AgentOrchestrator {
    return this.agentOrchestrator;
  }

  getSafetyManager(): SafetyManager {
    return this.safetyManager;
  }

  getAuthorityGate(): AuthorityGate {
    return this.authorityGate;
  }
}
