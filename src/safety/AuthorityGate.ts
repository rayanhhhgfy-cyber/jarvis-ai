import { createLogger } from "../utils/logger";
import type { ConfigManager } from "../config/ConfigManager";

const log = createLogger("authority-gate");

export interface GateCheck {
  allowed: boolean;
  reason?: string;
  requiresApproval?: boolean;
}

export class AuthorityGate {
  private configManager: ConfigManager;

  constructor(configManager: ConfigManager) {
    this.configManager = configManager;
  }

  check(
    toolName: string,
    toolLevel: number,
    agentLevel: number,
    category?: string,
  ): GateCheck {
    const safety = this.configManager.get<Record<string, unknown>>("safety") || {};

    // Check emergency pause
    if (safety.emergencyPause) {
      return { allowed: false, reason: "Emergency pause is active" };
    }

    // Check no-local-tools mode
    if (safety.noLocalTools && !category?.includes("remote")) {
      return { allowed: false, reason: "Local tools disabled (--no-local-tools mode)" };
    }

    // Check authority level
    if (agentLevel < toolLevel) {
      return {
        allowed: false,
        reason: `Agent level ${agentLevel} < required level ${toolLevel} for tool "${toolName}"`,
      };
    }

    // Check governed categories
    const governedCategories = (safety.governedCategories as string[]) || [];
    if (category && governedCategories.includes(category)) {
      return { allowed: true, requiresApproval: true };
    }

    return { allowed: true };
  }
}
