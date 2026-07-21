import { createLogger } from "../utils/logger";
import type { ConfigManager } from "../config/ConfigManager";

const log = createLogger("safety-manager");

export class SafetyManager {
  private configManager: ConfigManager;
  private emergencyPaused = false;

  constructor(configManager: ConfigManager) {
    this.configManager = configManager;
    log.info("SafetyManager initialized");
  }

  pause(): void {
    this.emergencyPaused = true;
    this.configManager.set("safety.emergencyPause", true);
    log.warn("EMERGENCY PAUSE ACTIVATED - all tool execution suspended");
  }

  resume(): void {
    this.emergencyPaused = false;
    this.configManager.set("safety.emergencyPause", false);
    log.info("Emergency pause deactivated - tool execution resumed");
  }

  isPaused(): boolean {
    return this.emergencyPaused || this.configManager.get<boolean>("safety.emergencyPause") || false;
  }

  validateOutput(data: string, maxSize?: number): string {
    const limit = maxSize || this.configManager.get<number>("safety.outputTruncationSize") || 10240;
    if (data.length > limit) {
      return data.slice(0, limit) + `\n... [truncated at ${limit} bytes]`;
    }
    return data;
  }

  validateFileRead(size: number): boolean {
    const maxSize = this.configManager.get<number>("safety.maxFileReadSize") || 102400;
    return size <= maxSize;
  }

  sanitizeSidecarData(data: Record<string, unknown>): Record<string, unknown> {
    const maxJsonSize = this.configManager.get<number>("sidecar.maxJsonSize") || 1048576;
    const serialized = JSON.stringify(data);
    if (serialized.length > maxJsonSize) {
      throw new Error(`Sidecar data exceeds max JSON size of ${maxJsonSize} bytes`);
    }
    // Prototype pollution sanitization
    const sanitized = JSON.parse(serialized);
    this.sanitizeObject(sanitized);
    return sanitized;
  }

  private sanitizeObject(obj: Record<string, unknown>): void {
    for (const key of Object.keys(obj)) {
      if (key === "__proto__" || key === "constructor" || key === "prototype") {
        delete obj[key];
      } else if (typeof obj[key] === "object" && obj[key] !== null && !Array.isArray(obj[key])) {
        this.sanitizeObject(obj[key] as Record<string, unknown>);
      }
    }
  }
}
