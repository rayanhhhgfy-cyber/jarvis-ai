import { createLogger } from "../utils/logger";
import type { LLMManager } from "../llm/LLMManager";
import type { ToolRegistry } from "../tools/index";
import type { Vault } from "../vault/Vault";
import type { ConfigManager } from "../config/ConfigManager";
import type { LLMMessage, ToolDefinition } from "../llm/types";
import { RoleLoader } from "./RoleLoader";
import { ToolExecutor } from "./ToolExecutor";
import type { AgentRole, AgentState, SubAgentInfo } from "./types";

const log = createLogger("agent-orch");

export class AgentOrchestrator {
  private llmManager: LLMManager;
  private toolRegistry: ToolRegistry;
  private vault: Vault;
  private configManager: ConfigManager;
  private toolExecutor: ToolExecutor;
  private roleLoader: RoleLoader;
  private agents: Map<string, AgentState> = new Map();
  private subAgents: Map<string, SubAgentInfo> = new Map();

  constructor(
    llmManager: LLMManager,
    toolRegistry: ToolRegistry,
    vault: Vault,
    configManager: ConfigManager,
  ) {
    this.llmManager = llmManager;
    this.toolRegistry = toolRegistry;
    this.vault = vault;
    this.configManager = configManager;
    this.toolExecutor = new ToolExecutor(toolRegistry, vault, configManager, llmManager);
    this.roleLoader = new RoleLoader();
  }

  async initialize(): Promise<string> {
    const rolePath = this.configManager.get<string>("agent.rolePath") || "./roles/personal-assistant.yaml";
    const role = this.roleLoader.load(rolePath);
    const defaultLevel = this.configManager.get<number>("agent.defaultLevel") || 3;

    const agentRecord = this.vault.createAgent(role.name, role.name, role.allowedLevel || defaultLevel);
    const conversation = this.vault.createConversation(`${role.name} session`);

    const state: AgentState = {
      id: agentRecord.id,
      role,
      conversationId: conversation.id,
      messages: [
        { role: "system", content: role.systemPrompt },
      ],
      iteration: 0,
      parentId: null,
      status: "idle",
    };

    this.agents.set(agentRecord.id, state);
    log.info(`Agent initialized: ${agentRecord.id} (role: ${role.name})`);
    return agentRecord.id;
  }

  async processMessage(agentId: string, userMessage: string): Promise<string> {
    const agent = this.agents.get(agentId);
    if (!agent) throw new Error(`Agent not found: ${agentId}`);

    agent.messages.push({ role: "user", content: userMessage });
    this.vault.addMessage(agent.conversationId, "user", userMessage);
    agent.status = "thinking";

    try {
      const result = await this.runToolLoop(agent);
      agent.status = "done";
      return result;
    } catch (err) {
      agent.status = "error";
      const errorMsg = (err as Error).message;
      log.error(`Agent ${agentId} failed`, { error: errorMsg });
      return `Error: ${errorMsg}`;
    }
  }

  private async runToolLoop(agent: AgentState): Promise<string> {
    const maxIterations = agent.role.maxIterations || 200;

    while (agent.iteration < maxIterations) {
      agent.iteration++;
      agent.status = "thinking";

      // Get allowed tools for this agent
      const availableTools = this.toolRegistry.getAllTools()
        .filter(t => agent.role.tools.includes(t.name) && t.requiredLevel <= agent.role.allowedLevel)
        .map(t => ({
          type: "function" as const,
          function: {
            name: t.name,
            description: t.description,
            parameters: t.parameters as Record<string, unknown>,
          },
        }));

      // Validate message history before LLM call
      for (let i = 0; i < agent.messages.length; i++) {
        const m = agent.messages[i];
        if (m.role === "assistant" && m.tool_calls && m.tool_calls.length > 0) {
          const next = agent.messages[i + 1];
          if (!next || next.role !== "tool") {
            log.error(`INVALID MESSAGE HISTORY at index ${i}: assistant with tool_calls not followed by tool messages`, {
              tool_call_ids: m.tool_calls.map(tc => tc.id),
              nextRole: next?.role,
            });
          }
        }
      }

      // Get LLM response
      const response = await this.llmManager.generate(
        agent.messages,
        availableTools,
        agent.role.temperature,
        agent.role.maxTokens,
      );

      const hasToolCalls = response.tool_calls && response.tool_calls.length > 0;
      const responseMsg: LLMMessage = {
        role: "assistant",
        content: hasToolCalls ? null : response.content,
      };

      if (hasToolCalls) {
        responseMsg.tool_calls = response.tool_calls;
        const tcs = response.tool_calls!;
        log.info(`LLM returned ${tcs.length} tool call(s)`, {
          ids: tcs.map(tc => tc.id),
          names: tcs.map(tc => tc.function.name),
        });
      }

      agent.messages.push(responseMsg);
      this.vault.addMessage(
        agent.conversationId, "assistant", response.content || "",
        JSON.stringify(response.tool_calls || []),
        "[]", response.usage?.total_tokens,
      );

      // Execute tool calls if any
      if (response.tool_calls && response.tool_calls.length > 0) {
        agent.status = "executing";

        for (const toolCall of response.tool_calls) {
          const toolName = toolCall.function.name;
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(toolCall.function.arguments);
          } catch {
            args = {};
          }

          log.info(`Agent executing: ${toolName}`, { args, iteration: agent.iteration, callId: toolCall.id });

          const result = await this.toolExecutor.execute(
            toolName, args, agent.id, agent.role.allowedLevel,
          );

          const resultMsg: LLMMessage = {
            role: "tool",
            content: JSON.stringify(result),
            tool_call_id: toolCall.id,
          };
          agent.messages.push(resultMsg);
          log.info(`Tool result pushed for callId: ${toolCall.id}`);
          this.vault.addMessage(
            agent.conversationId, "tool", JSON.stringify(result),
            "[]", "[]", 0,
          );
        }
      } else {
        // No tool calls - this is the final response
        agent.status = "done";
        return response.content || "";
      }
    }

    agent.status = "done";
    return "Task completed after maximum iterations.";
  }

  async delegateTask(parentAgentId: string, task: string, agentType: string): Promise<string> {
    const parent = this.agents.get(parentAgentId);
    if (!parent) throw new Error(`Parent agent not found: ${parentAgentId}`);

    const subRole: AgentRole = {
      ...this.roleLoader.getDefaultRole(),
      name: `${agentType}-agent`,
      description: `Specialist ${agentType} agent`,
      systemPrompt: `You are a specialist ${agentType} agent. Your task: ${task}\nComplete this task using your available tools. Report results back to the parent agent.`,
      tools: parent.role.tools,
      subAgents: [],
      allowedLevel: parent.role.allowedLevel,
    };

    const subAgentRecord = this.vault.createAgent(
      `${agentType}-agent`, agentType,
      parent.role.allowedLevel, parentAgentId,
    );
    const subConversation = this.vault.createConversation(`${agentType} task`);

    const subState: AgentState = {
      id: subAgentRecord.id,
      role: subRole,
      conversationId: subConversation.id,
      messages: [
        { role: "system", content: subRole.systemPrompt },
        { role: "user", content: task },
      ],
      iteration: 0,
      parentId: parentAgentId,
      status: "idle",
    };

    this.agents.set(subAgentRecord.id, subState);

    const subInfo: SubAgentInfo = {
      id: subAgentRecord.id,
      name: subRole.name,
      role: agentType,
      status: "running",
      task,
    };
    this.subAgents.set(subAgentRecord.id, subInfo);

    // Run the sub-agent asynchronously
    this.runSubAgent(subAgentRecord.id).catch(err => {
      log.error(`Sub-agent ${subAgentRecord.id} failed`, { error: (err as Error).message });
      const info = this.subAgents.get(subAgentRecord.id);
      if (info) {
        info.status = "error";
        info.error = (err as Error).message;
      }
    });

    return subAgentRecord.id;
  }

  private async runSubAgent(agentId: string): Promise<void> {
    const agent = this.agents.get(agentId);
    if (!agent) throw new Error(`Sub-agent not found: ${agentId}`);

    const result = await this.runToolLoop(agent);

    const info = this.subAgents.get(agentId);
    if (info) {
      info.status = "completed";
      info.result = result;
    }

    // Report back to parent
    if (agent.parentId) {
      const parent = this.agents.get(agent.parentId);
      if (parent) {
        parent.messages.push({
          role: "user",
          content: `[Sub-agent ${agent.role.name} completed]\nTask result: ${result}`,
        });
      }
    }
  }

  getAgentState(agentId: string): AgentState | undefined {
    return this.agents.get(agentId);
  }

  getSubAgentInfo(agentId: string): SubAgentInfo | undefined {
    return this.subAgents.get(agentId);
  }

  listSubAgents(): SubAgentInfo[] {
    return Array.from(this.subAgents.values());
  }

  listAgents(): AgentState[] {
    return Array.from(this.agents.values());
  }

  getToolExecutor(): ToolExecutor {
    return this.toolExecutor;
  }
}
