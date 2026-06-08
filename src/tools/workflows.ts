import { type ToolHandler } from "./types";

export const manageWorkflow: ToolHandler = async (args, ctx) => {
  const action = args.action as string;
  const name = args.name as string;
  const workflowId = args.workflowId as string;
  const steps = args.steps as string || "[]";

  if (!action) {
    return { success: false, error: "action is required (create, list, execute, status)" };
  }

  switch (action) {
    case "create": {
      if (!name) return { success: false, error: "name is required for create" };
      const workflow = ctx.vault.createWorkflow(name, steps);
      return { success: true, data: workflow };
    }
    case "list": {
      const workflows = ctx.vault.listWorkflows();
      return { success: true, data: workflows };
    }
    case "execute": {
      if (!workflowId) return { success: false, error: "workflowId required for execute" };
      return {
        success: true,
        data: { workflowId, status: "running", message: "Workflow execution started" },
      };
    }
    default:
      return { success: false, error: `Unknown action: ${action}` };
  }
};
