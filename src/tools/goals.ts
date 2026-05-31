import { type ToolHandler } from "./types";

export const manageGoals: ToolHandler = async (args, ctx) => {
  const action = args.action as string;
  const title = args.title as string;
  const goalId = args.goalId as string;
  const keyResults = args.keyResults as string || "[]";
  const progress = args.progress as number;

  if (!action) {
    return { success: false, error: "action is required (create, list, update, delete)" };
  }

  switch (action) {
    case "create": {
      if (!title) return { success: false, error: "title is required for create" };
      const goal = ctx.vault.createGoal(title, keyResults);
      return { success: true, data: goal };
    }
    case "list": {
      const goals = ctx.vault.listGoals();
      return { success: true, data: goals };
    }
    case "update": {
      if (!goalId) return { success: false, error: "goalId required for update" };
      if (progress !== undefined) {
        ctx.vault.updateGoalProgress(goalId, progress);
      }
      return { success: true, data: { id: goalId, updated: true } };
    }
    default:
      return { success: false, error: `Unknown action: ${action}` };
  }
};
