import { type ToolDefinition, type ToolContext, type ToolResult } from "./types";
import { runCommand } from "./terminal";
import { readFile, writeFile, listDirectory } from "./fileops";
import {
  browserNavigate, browserClick, browserType, browserScroll,
  browserSnapshot, browserScreenshot, browserEvaluate, browserUploadFile,
} from "./browser";
import { getClipboard, setClipboard } from "./clipboard";
import { captureScreen } from "./screen";
import { getSystemInfo } from "./system";
import { delegateTask } from "./delegate";
import { manageAgents } from "./agents";
import { contentPipeline } from "./content";
import { manageGoals } from "./goals";
import { manageWorkflow } from "./workflows";
import { desktopType, desktopClick, desktopScreenshot } from "./desktop";
import { deepResearch, backgroundCheck, webFetch, analyzeData } from "./research";

export class ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map();

  constructor() {
    this.registerAll();
  }

  private registerAll(): void {
    this.register({
      name: "run_command", description: "Execute shell commands on the system",
      category: "terminal", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { command: { type: "string", description: "Command to execute" }, timeout: { type: "number", description: "Timeout in ms" }, cwd: { type: "string", description: "Working directory" } }, required: ["command"] },
      execute: runCommand,
    });
    this.register({
      name: "read_file", description: "Read contents of a file",
      category: "filesystem", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { path: { type: "string", description: "File path" }, maxSize: { type: "number", description: "Max bytes to read" } }, required: ["path"] },
      execute: readFile,
    });
    this.register({
      name: "write_file", description: "Write content to a file",
      category: "filesystem", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { path: { type: "string", description: "File path" }, content: { type: "string", description: "Content to write" } }, required: ["path", "content"] },
      execute: writeFile,
    });
    this.register({
      name: "list_directory", description: "List files and directories",
      category: "filesystem", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { path: { type: "string", description: "Directory path" } }, required: ["path"] },
      execute: listDirectory,
    });
    this.register({
      name: "browser_navigate", description: "Navigate browser to a URL",
      category: "browser", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { url: { type: "string", description: "URL to navigate to" }, sessionId: { type: "string" } }, required: ["url"] },
      execute: browserNavigate,
    });
    this.register({
      name: "browser_click", description: "Click an element on the page",
      category: "browser", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { sessionId: { type: "string" }, selector: { type: "string" } }, required: ["sessionId", "selector"] },
      execute: browserClick,
    });
    this.register({
      name: "browser_type", description: "Type text into an input field",
      category: "browser", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { sessionId: { type: "string" }, selector: { type: "string" }, text: { type: "string" } }, required: ["sessionId", "selector", "text"] },
      execute: browserType,
    });
    this.register({
      name: "browser_scroll", description: "Scroll the browser page",
      category: "browser", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { sessionId: { type: "string" }, direction: { type: "string", enum: ["up", "down"] } } },
      execute: browserScroll,
    });
    this.register({
      name: "browser_snapshot", description: "Get the current page HTML snapshot",
      category: "browser", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { sessionId: { type: "string" } }, required: ["sessionId"] },
      execute: browserSnapshot,
    });
    this.register({
      name: "browser_screenshot", description: "Take a screenshot of the browser",
      category: "browser", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { sessionId: { type: "string" } } },
      execute: browserScreenshot,
    });
    this.register({
      name: "browser_evaluate", description: "Run JavaScript code in the browser page",
      category: "browser", requiredLevel: 3, governed: true,
      parameters: { type: "object", properties: { code: { type: "string", description: "JavaScript code" } }, required: ["code"] },
      execute: browserEvaluate,
    });
    this.register({
      name: "browser_upload_file", description: "Upload a file through the browser",
      category: "browser", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { selector: { type: "string" }, filepath: { type: "string" } }, required: ["selector", "filepath"] },
      execute: browserUploadFile,
    });
    this.register({
      name: "get_clipboard", description: "Get the current clipboard contents",
      category: "system", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: {} },
      execute: getClipboard,
    });
    this.register({
      name: "set_clipboard", description: "Set the clipboard contents",
      category: "system", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
      execute: setClipboard,
    });
    this.register({
      name: "capture_screen", description: "Capture the main screen",
      category: "system", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: {} },
      execute: captureScreen,
    });
    this.register({
      name: "get_system_info", description: "Get detailed system information",
      category: "system", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: {} },
      execute: getSystemInfo,
    });
    this.register({
      name: "delegate_task", description: "Delegate a task to a specialist sub-agent",
      category: "delegation", requiredLevel: 3, governed: false,
      parameters: { type: "object", properties: { task: { type: "string" }, agentType: { type: "string" }, params: { type: "object" } }, required: ["task"] },
      execute: delegateTask,
    });
    this.register({
      name: "manage_agents", description: "Create, list, update, delete, pause, or resume agents",
      category: "agents", requiredLevel: 3, governed: true,
      parameters: { type: "object", properties: { action: { type: "string", enum: ["create", "list", "update", "delete", "pause", "resume"] }, agentId: { type: "string" }, config: { type: "object" } }, required: ["action"] },
      execute: manageAgents,
    });
    this.register({
      name: "content_pipeline", description: "Generate and publish content (blog, video, social, email)",
      category: "content", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { title: { type: "string" }, type: { type: "string" }, platform: { type: "string" }, content: { type: "string" } }, required: ["title", "content"] },
      execute: contentPipeline,
    });
    this.register({
      name: "manage_goals", description: "Create and manage OKR goals",
      category: "goals", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { action: { type: "string" }, title: { type: "string" }, goalId: { type: "string" }, keyResults: { type: "string" }, progress: { type: "number" } }, required: ["action"] },
      execute: manageGoals,
    });
    this.register({
      name: "manage_workflow", description: "Create and execute workflows",
      category: "workflows", requiredLevel: 3, governed: true,
      parameters: { type: "object", properties: { action: { type: "string" }, name: { type: "string" }, workflowId: { type: "string" }, steps: { type: "string" } }, required: ["action"] },
      execute: manageWorkflow,
    });
    this.register({
      name: "desktop_type", description: "Type text into a desktop application window",
      category: "desktop", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { pid: { type: "number" }, text: { type: "string" } }, required: ["text"] },
      execute: desktopType,
    });
    this.register({
      name: "desktop_click", description: "Click at screen coordinates",
      category: "desktop", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { x: { type: "number" }, y: { type: "number" } }, required: ["x", "y"] },
      execute: desktopClick,
    });
    this.register({
      name: "desktop_screenshot", description: "Capture a desktop application window screenshot",
      category: "desktop", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { pid: { type: "number" } } },
      execute: desktopScreenshot,
    });

    // Research & Intelligence tools
    this.register({
      name: "deep_research", description: "Perform deep multi-source research on any topic with LLM synthesis",
      category: "research", requiredLevel: 2, governed: false,
      parameters: { type: "object", properties: { query: { type: "string", description: "Research query" }, depth: { type: "number", description: "Research depth (1-5)" }, sources: { type: "string", description: "Comma-separated source types" } }, required: ["query"] },
      execute: deepResearch,
    });
    this.register({
      name: "background_check", description: "Perform professional background checks on people, companies, or entities",
      category: "research", requiredLevel: 3, governed: false,
      parameters: { type: "object", properties: { target: { type: "string", description: "Person, company, or entity name" }, context: { type: "string", description: "Additional context" }, type: { type: "string", description: "Check type (general, security, professional)" } }, required: ["target"] },
      execute: backgroundCheck,
    });
    this.register({
      name: "web_fetch", description: "Fetch and extract content from any URL",
      category: "research", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { url: { type: "string", description: "URL to fetch" }, format: { type: "string", enum: ["markdown", "html", "json", "text"] } }, required: ["url"] },
      execute: webFetch,
    });
    this.register({
      name: "analyze_data", description: "Analyze data using LLM for insights, patterns, anomalies and summaries",
      category: "research", requiredLevel: 1, governed: false,
      parameters: { type: "object", properties: { data: { type: "string", description: "Data to analyze" }, type: { type: "string", description: "Analysis type (summary, pattern, anomaly, sentiment)" }, context: { type: "string" } }, required: ["data"] },
      execute: analyzeData,
    });
  }

  private register(tool: ToolDefinition): void {
    this.tools.set(tool.name, tool);
  }

  getTool(name: string): ToolDefinition | undefined {
    return this.tools.get(name);
  }

  getAllTools(): ToolDefinition[] {
    return Array.from(this.tools.values());
  }

  getToolSchemas(): Array<Record<string, unknown>> {
    return this.getAllTools().map(t => ({
      type: "function",
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      },
    }));
  }

  async executeTool(name: string, args: Record<string, unknown>, ctx: ToolContext): Promise<ToolResult> {
    const tool = this.tools.get(name);
    if (!tool) {
      return { success: false, error: `Unknown tool: ${name}` };
    }

    // Authority gate: check level
    if (ctx.agentLevel < tool.requiredLevel) {
      return {
        success: false,
        error: `Agent level ${ctx.agentLevel} insufficient for tool "${name}" (requires level ${tool.requiredLevel})`,
      };
    }

    // Governed category check
    if (tool.governed && ctx.onApproval) {
      const approved = await ctx.onApproval(`execute:${name}`, { tool: name, args });
      if (!approved) {
        return { success: false, error: `Tool "${name}" execution denied by user` };
      }
    }

    // Audit log
    ctx.vault.addAuditLog(ctx.agentId, `tool:${name}`, "info", name, JSON.stringify(args));

    return tool.execute(args, ctx);
  }
}
