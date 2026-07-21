import { type ToolHandler } from "./types";

export const delegateTask: ToolHandler = async (args, ctx) => {
  const task = args.task as string;
  const agentType = args.agentType as string || "general";
  const params = args.params as Record<string, unknown> || {};

  if (!task) {
    return { success: false, error: "task is required" };
  }

  return {
    success: true,
    data: {
      message: `Task delegated to ${agentType} agent`,
      task,
      agentType,
      params,
      note: "Sub-agent execution handled by AgentOrchestrator",
    },
  };
};
