import { createLogger } from "../../utils/logger";
import type { Service } from "../ServiceRegistry";

const log = createLogger("site-builder");

export class SiteBuilderService implements Service {
  name = "site-builder";
  private running = false;

  async start(): Promise<void> {
    log.info("Site builder service started (inactive)");
    this.running = true;
  }

  async stop(): Promise<void> {
    this.running = false;
    log.info("Site builder service stopped");
  }

  isRunning(): boolean {
    return this.running;
  }
}
