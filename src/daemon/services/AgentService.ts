import { createLogger } from "../../utils/logger";
import type { AgentOrchestrator } from "../../agents/AgentOrchestrator";
import type { Service } from "../ServiceRegistry";

const log = createLogger("agent-service");

export class AgentService implements Service {
  name = "agent";
  private orchestrator: AgentOrchestrator;
  private agentId: string | null = null;
  private running = false;

  constructor(orchestrator: AgentOrchestrator) {
    this.orchestrator = orchestrator;
  }

  async start(): Promise<void> {
    this.agentId = await this.orchestrator.initialize();
    this.running = true;
    log.info(`Agent service started (ID: ${this.agentId})`);
  }

  async stop(): Promise<void> {
    this.running = false;
    log.info("Agent service stopped");
  }

  isRunning(): boolean {
    return this.running;
  }

  getAgentId(): string | null {
    return this.agentId;
  }

  getOrchestrator(): AgentOrchestrator {
    return this.orchestrator;
  }
}
