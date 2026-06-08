import { createLogger } from "../utils/logger";
import type { ToolRegistry } from "../tools/index";
import type { Vault } from "../vault/Vault";
import type { ConfigManager } from "../config/ConfigManager";
import type { LLMManager } from "../llm/LLMManager";
import type { ToolContext, ToolResult } from "../tools/types";

const log = createLogger("tool-executor");

export class ToolExecutor {
  private toolRegistry: ToolRegistry;
  private vault: Vault;
  private configManager: ConfigManager;
  private llmManager: LLMManager;
  private pendingApprovals: Map<string, (approved: boolean) => void> = new Map();

  constructor(
    toolRegistry: ToolRegistry,
    vault: Vault,
    configManager: ConfigManager,
    llmManager: LLMManager,
  ) {
    this.toolRegistry = toolRegistry;
    this.vault = vault;
    this.configManager = configManager;
    this.llmManager = llmManager;
  }

  async execute(
    toolName: string,
    args: Record<string, unknown>,
    agentId: string,
    agentLevel: number,
  ): Promise<ToolResult> {
    const startTime = Date.now();

    const ctx: ToolContext = {
      agentId,
      agentLevel,
      configManager: this.configManager,
      vault: this.vault,
      llmManager: this.llmManager,
      onApproval: async (action, details) => {
        return this.requestApproval(agentId, action, details);
      },
    };

    // Log the tool call
    const toolCall = this.vault.createToolCall(agentId, toolName, JSON.stringify(args));

    try {
      const result = await this.toolRegistry.executeTool(toolName, args, ctx);
      const duration = Date.now() - startTime;

      this.vault.completeToolCall(
        toolCall.id,
        JSON.stringify(result),
        result.success ? "success" : "error",
        duration,
      );

      if (result.success) {
        log.info(`Tool ${toolName} completed`, { duration: `${duration}ms` });
      } else {
        log.warn(`Tool ${toolName} failed`, { error: result.error });
      }

      return result;
    } catch (err) {
      const duration = Date.now() - startTime;
      const errorMessage = (err as Error).message;
      this.vault.completeToolCall(toolCall.id, errorMessage, "error", duration);
      log.error(`Tool ${toolName} threw exception`, { error: errorMessage });
      return { success: false, error: errorMessage };
    }
  }

  private async requestApproval(
    agentId: string,
    action: string,
    details: Record<string, unknown>,
  ): Promise<boolean> {
    const approval = this.vault.createApproval(agentId, action, JSON.stringify(details));
    log.info(`Approval requested: ${action}`, { approvalId: approval.id });

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        this.pendingApprovals.delete(approval.id);
        this.vault.resolveApproval(approval.id, "denied");
        resolve(false);
      }, 60000);

      this.pendingApprovals.set(approval.id, (approved: boolean) => {
        clearTimeout(timeout);
        this.vault.resolveApproval(approval.id, approved ? "approved" : "denied");
        resolve(approved);
      });
    });
  }

  resolveApproval(approvalId: string, approved: boolean): boolean {
    const resolver = this.pendingApprovals.get(approvalId);
    if (resolver) {
      resolver(approved);
      this.pendingApprovals.delete(approvalId);
      return true;
    }
    return false;
  }

  getPendingApprovals(): Array<{ id: string; action: string; details: string }> {
    return this.vault.getPendingApprovals().map(a => ({
      id: a.id,
      action: a.action,
      details: a.details,
    }));
  }
}
