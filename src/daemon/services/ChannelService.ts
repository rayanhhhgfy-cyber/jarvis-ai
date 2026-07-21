import { createLogger } from "../../utils/logger";
import type { Service } from "../ServiceRegistry";

const log = createLogger("channels");

export class ChannelService implements Service {
  name = "channels";
  private running = false;

  async start(): Promise<void> {
    log.info("Channel service started (no channels configured)");
    this.running = true;
  }

  async stop(): Promise<void> {
    this.running = false;
    log.info("Channel service stopped");
  }

  isRunning(): boolean {
    return this.running;
  }
}
