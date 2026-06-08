import { createLogger } from "../../utils/logger";
import type { Service } from "../ServiceRegistry";
import type { Vault } from "../../vault/Vault";

const log = createLogger("sidecar");

export class SidecarService implements Service {
  name = "sidecar-manager";
  private vault: Vault;
  private running = false;
  private server: { stop: () => void } | null = null;

  constructor(vault: Vault) {
    this.vault = vault;
  }

  async start(): Promise<void> {
    const sidecars = this.vault.listSidecars();
    log.info(`Sidecar service started. ${sidecars.length} enrolled sidecar(s)`);
    this.running = true;
  }

  async stop(): Promise<void> {
    if (this.server) {
      this.server.stop();
      this.server = null;
    }
    this.running = false;
    log.info("Sidecar service stopped");
  }

  isRunning(): boolean {
    return this.running;
  }
}
