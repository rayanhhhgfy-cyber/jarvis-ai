import { createLogger } from "../../utils/logger";
import type { Service } from "../ServiceRegistry";

const log = createLogger("heartbeat");

export class HeartbeatService implements Service {
  name = "heartbeat";
  private interval: ReturnType<typeof setInterval> | null = null;
  private heartbeats = 0;

  async start(): Promise<void> {
    this.interval = setInterval(() => {
      this.heartbeats++;
      const uptime = process.uptime();
      log.info(`Heartbeat #${this.heartbeats} - Uptime: ${Math.floor(uptime)}s`, {
        heartbeats: this.heartbeats,
        uptime: Math.floor(uptime),
        memory: process.memoryUsage().rss,
      });
    }, 30000);
    log.info("Heartbeat service started (30s interval)");
  }

  async stop(): Promise<void> {
    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
    log.info("Heartbeat service stopped");
  }

  isRunning(): boolean {
    return this.interval !== null;
  }

  getHeartbeatCount(): number {
    return this.heartbeats;
  }
}
