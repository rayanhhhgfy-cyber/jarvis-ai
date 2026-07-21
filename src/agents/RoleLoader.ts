import { readFileSync, existsSync } from "fs";
import { createLogger } from "../utils/logger";
import type { AgentRole } from "./types";

const log = createLogger("role-loader");

const DEFAULT_ROLE: AgentRole = {
  name: "personal-assistant",
  description: "A general-purpose AI assistant that helps with tasks, answers questions, and automates workflows",
  systemPrompt: `You are Jarvis Omega, an always-on autonomous AI assistant.
You have access to various tools to help you accomplish tasks.
Think step by step, use the right tools for each part of the task, and report results clearly.
Be proactive and efficient. If a task requires multiple steps, plan them out.
If you need to delegate to a specialist sub-agent, use the delegate_task tool.
Always consider safety - don't execute destructive commands without confirmation.`,
  model: "claude-sonnet-4-20250514",
  temperature: 0.7,
  maxTokens: 4096,
  maxIterations: 200,
  tools: [
    "run_command", "read_file", "write_file", "list_directory",
    "browser_navigate", "browser_click", "browser_type", "browser_scroll",
    "browser_snapshot", "browser_screenshot", "browser_evaluate", "browser_upload_file",
    "get_clipboard", "set_clipboard", "capture_screen", "get_system_info",
    "delegate_task", "manage_agents", "content_pipeline", "manage_goals", "manage_workflow",
    "desktop_type", "desktop_click", "desktop_screenshot",
  ],
  subAgents: ["code", "research", "browser", "os", "planner"],
  allowedLevel: 3,
  safety: {
    requireApproval: ["filesystem_delete", "system_shutdown", "network_modify"],
    denyTools: [],
    maxConcurrency: 5,
  },
};

export class RoleLoader {
  private cache: Map<string, AgentRole> = new Map();

  constructor() {
    this.cache.set("personal-assistant", DEFAULT_ROLE);
  }

  load(rolePath: string): AgentRole {
    if (this.cache.has(rolePath)) {
      return this.cache.get(rolePath)!;
    }

    // Try direct path
    if (existsSync(rolePath)) {
      try {
        const content = readFileSync(rolePath, "utf-8");
        const role: AgentRole = JSON.parse(content);
        this.cache.set(rolePath, role);
        log.info(`Role loaded from ${rolePath}`);
        return role;
      } catch (err) {
        log.warn(`Failed to load role from ${rolePath}`, { error: (err as Error).message });
      }
    }

    // Try roles directory
    const rolesDir = import.meta.dir + "/roles/" + rolePath.replace(/.*[/\\]/, "");
    if (existsSync(rolesDir)) {
      try {
        const content = readFileSync(rolesDir, "utf-8");
        const role: AgentRole = JSON.parse(content);
        this.cache.set(rolePath, role);
        log.info(`Role loaded from ${rolesDir}`);
        return role;
      } catch { /* fall through */ }
    }

    log.warn(`Role not found, using default: ${rolePath}`);
    return { ...DEFAULT_ROLE };
  }

  getDefaultRole(): AgentRole {
    return { ...DEFAULT_ROLE };
  }
}
