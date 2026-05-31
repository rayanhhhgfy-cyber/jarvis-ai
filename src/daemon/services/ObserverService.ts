import { createLogger } from "../../utils/logger";
import type { Service } from "../ServiceRegistry";

const log = createLogger("observers");

export class ObserverService implements Service {
  name = "observers";
  private running = false;
  private timers: ReturnType<typeof setInterval>[] = [];

  async start(): Promise<void> {
    log.info("Observer service started (no active observers configured)");
    this.running = true;
  }

  async stop(): Promise<void> {
    for (const timer of this.timers) {
      clearInterval(timer);
    }
    this.timers = [];
    this.running = false;
    log.info("Observer service stopped");
  }

  isRunning(): boolean {
    return this.running;
  }
}
