import { createLogger } from "../utils/logger";

const log = createLogger("service-registry");

export interface Service {
  name: string;
  start(): Promise<void>;
  stop(): Promise<void>;
  isRunning(): boolean;
}

export class ServiceRegistry {
  private services: Map<string, Service> = new Map();
  private startOrder: string[] = [];
  private running = false;

  register(service: Service, dependsOn?: string[]): void {
    if (this.services.has(service.name)) {
      log.warn(`Service "${service.name}" already registered, overwriting`);
    }
    this.services.set(service.name, service);
    this.startOrder.push(service.name);
    log.info(`Registered service: ${service.name}`);
  }

  async startAll(): Promise<void> {
    if (this.running) {
      log.warn("Services already running");
      return;
    }

    log.info(`Starting ${this.services.size} services...`);

    for (const name of this.startOrder) {
      const service = this.services.get(name);
      if (!service) continue;

      try {
        log.info(`Starting service: ${name}`);
        await service.start();
        log.info(`Service started: ${name}`);
      } catch (err) {
        log.error(`Failed to start service: ${name}`, { error: (err as Error).message });
        // Don't block other services from starting
      }
    }

    this.running = true;
    log.info("All services started");
  }

  async stopAll(): Promise<void> {
    if (!this.running) return;

    log.info("Stopping all services...");

    // Stop in reverse order
    for (const name of this.startOrder.reverse()) {
      const service = this.services.get(name);
      if (!service) continue;

      try {
        await service.stop();
        log.info(`Service stopped: ${name}`);
      } catch (err) {
        log.error(`Failed to stop service: ${name}`, { error: (err as Error).message });
      }
    }

    this.running = false;
    log.info("All services stopped");
  }

  getService<T extends Service>(name: string): T | undefined {
    return this.services.get(name) as T | undefined;
  }

  listServices(): string[] {
    return Array.from(this.services.keys());
  }

  isRunning(): boolean {
    return this.running;
  }
}
