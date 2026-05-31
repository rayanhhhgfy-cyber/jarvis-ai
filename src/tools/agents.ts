import { type ToolHandler } from "./types";

export const manageAgents: ToolHandler = async (args, ctx) => {
  const action = args.action as string;
  const agentId = args.agentId as string;
  const config = args.config as Record<string, unknown> || {};

  if (!action) {
    return { success: false, error: "action is required (create, list, update, delete, pause, resume)" };
  }

  switch (action) {
    case "create": {
      const agent = ctx.vault.createAgent(
        config.name as string || "unnamed",
        config.role as string || "assistant",
        (config.level as number) || 3
      );
      return { success: true, data: agent };
    }
    case "list": {
      const agents = ctx.vault.listAgents();
      return { success: true, data: agents };
    }
    case "update": {
      if (!agentId) return { success: false, error: "agentId required for update" };
      const updates: Record<string, unknown> = {};
      if (config.status) updates.status = String(config.status);
      if (config.config) updates.config = String(config.config);
      if (config.level !== undefined) updates.level = Number(config.level);
      ctx.vault.updateAgent(agentId, updates as Parameters<typeof ctx.vault.updateAgent>[1]);
      return { success: true, data: { id: agentId, updated: true } };
    }
    case "delete": {
      if (!agentId) return { success: false, error: "agentId required for delete" };
      ctx.vault.deleteAgent(agentId);
      return { success: true, data: { id: agentId, deleted: true } };
    }
    case "pause": {
      if (!agentId) return { success: false, error: "agentId required for pause" };
      ctx.vault.updateAgent(agentId, { status: "paused" });
      return { success: true, data: { id: agentId, status: "paused" } };
    }
    case "resume": {
      if (!agentId) return { success: false, error: "agentId required for resume" };
      ctx.vault.updateAgent(agentId, { status: "idle" });
      return { success: true, data: { id: agentId, status: "resumed" } };
    }
    default:
      return { success: false, error: `Unknown action: ${action}` };
  }
};
