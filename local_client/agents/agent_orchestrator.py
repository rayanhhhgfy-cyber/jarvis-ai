# ====================================================================
# JARVIS OMEGA — Agent Orchestrator (Supervisor Agent)
# ====================================================================
"""
Supervisor agent responsible for lifecycle management of specialized agents.
Spawns, monitors, terminates, and orchestrates tasks across the multi-agent network.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime

from shared.models import TaskDefinition, TaskResult, AgentInfo
from shared.constants import AgentType, AgentStatus, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_orchestrator")

class AgentOrchestrator:
    """
    Supervisor orchestrator managing specialized sub-agents.
    Acts as the master router and coordinator of the local multi-agent system.
    """

    def __init__(self) -> None:
        self.agent_id = "orchestrator_master"
        self.status = AgentStatus.IDLE
        self.sub_agents: Dict[str, AgentInfo] = {}
        self.active_tasks: Dict[str, TaskDefinition] = {}

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """
        Main execution point for the orchestrator.
        Decomposes, plans, and delegates the task to appropriate sub-agents.
        """
        log.info("orchestrator_executing_task", task_id=task.task_id, title=task.title)
        self.status = AgentStatus.RUNNING
        start_time = time.time()

        try:
            # 1. Parse or plan execution steps
            # In Phase 5, the orchestrator routes tasks directly or decomposes complex ones
            target_agent = task.agent_type
            
            if target_agent == AgentType.ORCHESTRATOR:
                # Self-orchestration (decomposition into subtasks)
                result_data = await self._decompose_and_run(task)
            else:
                # Delegate to specific specialized agent
                result_data = await self._delegate_to_agent(target_agent, task)

            elapsed = (time.time() - start_time) * 1000
            self.status = AgentStatus.IDLE

            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            self.status = AgentStatus.FAILED
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("orchestrator_task_failed", task_id=task.task_id, error=err_msg)

            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    def _resolve_agent_class(self, agent_type: AgentType):
        """
        Dynamically import the module/class implementing a given agent type.
        Raises ModuleNotFoundError/AttributeError if the agent is not implemented.
        """
        import importlib

        module_name = f"local_client.agents.agent_{agent_type.value}"
        class_name = f"Agent{agent_type.value.capitalize()}"
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    async def _delegate_to_agent(self, agent_type: AgentType, task: TaskDefinition) -> Dict[str, Any]:
        """Dynamically loads and delegates a task to a specialized agent."""
        log.info("delegating_task", agent_type=agent_type.value, task_id=task.task_id)

        # Spawn record in local registry
        agent_info = AgentInfo(
            agent_type=agent_type,
            task_id=task.task_id,
            parent_id=self.agent_id,
            status=AgentStatus.SPAWNING,
            current_task_description=task.description,
        )
        self.sub_agents[agent_info.agent_id] = agent_info

        try:
            try:
                agent_class = self._resolve_agent_class(agent_type)
            except (ModuleNotFoundError, AttributeError) as load_err:
                raise RuntimeError(
                    f"No sub-agent is available for type '{agent_type.value}'"
                ) from load_err

            agent_instance = agent_class()
            agent_info.status = AgentStatus.RUNNING
            agent_info.updated_at = datetime.utcnow()

            # Execute
            task.assigned_agent_id = agent_info.agent_id
            result: TaskResult = await agent_instance.execute_task(task)

            agent_info.status = (
                AgentStatus.COMPLETED if result.status == TaskStatus.COMPLETED else AgentStatus.FAILED
            )
            agent_info.updated_at = datetime.utcnow()

            if result.status == TaskStatus.FAILED:
                raise RuntimeError(f"Sub-agent execution failed: {result.error}")

            log.info("subagent_completed", agent_type=agent_type.value, task_id=task.task_id)
            return result.result or {}

        except Exception as e:
            agent_info.status = AgentStatus.FAILED
            agent_info.error = str(e)
            agent_info.updated_at = datetime.utcnow()
            log.error("subagent_failed", agent_type=agent_type.value, task_id=task.task_id, error=str(e))
            raise

    async def _plan_subtasks(self, task: TaskDefinition) -> List[Dict[str, Any]]:
        """
        Produce a list of subtask payloads for a high-level goal by invoking the
        Planner sub-agent. Returns an empty list if planning yields nothing.
        """
        goal = task.payload.get("goal") or task.description or task.title
        if not goal:
            return []

        log.info("orchestrator_auto_planning", task_id=task.task_id, goal=goal)
        plan_task = TaskDefinition(
            title=f"Plan: {task.title}",
            description=f"Decompose goal into executable subtasks: {goal}",
            agent_type=AgentType.PLANNER,
            parent_task_id=task.task_id,
            payload={"action": "decompose", "goal": goal},
        )

        try:
            plan_result = await self._delegate_to_agent(AgentType.PLANNER, plan_task)
        except Exception as e:
            log.error("auto_planning_failed", task_id=task.task_id, error=str(e))
            return []

        subtasks = plan_result.get("subtasks", []) if isinstance(plan_result, dict) else []
        log.info("orchestrator_plan_ready", task_id=task.task_id, steps=len(subtasks))
        return subtasks

    async def _decompose_and_run(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Decompose a complex task into multiple subtasks and fan them out across
        specialized sub-agents. When no subtasks are supplied, the Planner agent
        is used to generate a plan automatically.

        Each subtask is isolated: a single sub-agent failure is recorded but does
        not abort the whole mission (unless ``payload.continue_on_error`` is False),
        so partial progress is always returned.
        """
        subtasks_payloads = task.payload.get("subtasks", [])
        if not subtasks_payloads:
            subtasks_payloads = await self._plan_subtasks(task)

        if not subtasks_payloads:
            log.warning("no_subtasks_found_in_orchestration_task", task_id=task.task_id)
            return {"status": "no_steps_to_orchestrate", "orchestrated_results": []}

        continue_on_error = task.payload.get("continue_on_error", True)
        results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for index, sub_payload in enumerate(subtasks_payloads):
            try:
                sub_agent_type = AgentType(sub_payload.get("agent_type", "os"))
            except ValueError:
                log.warning("invalid_subtask_agent_type", agent_type=sub_payload.get("agent_type"))
                sub_agent_type = AgentType.OS

            sub_task = TaskDefinition(
                title=sub_payload.get("title", f"Subtask {index}"),
                description=sub_payload.get("description", ""),
                agent_type=sub_agent_type,
                parent_task_id=task.task_id,
                payload=sub_payload.get("payload", {}),
            )

            task.subtasks.append(sub_task.task_id)
            log.info("running_orchestrated_subtask", parent_id=task.task_id, subtask_id=sub_task.task_id)

            try:
                sub_result = await self._delegate_to_agent(sub_agent_type, sub_task)
                succeeded += 1
                results.append({
                    "subtask_id": sub_task.task_id,
                    "agent_type": sub_agent_type.value,
                    "status": TaskStatus.COMPLETED.value,
                    "result": sub_result,
                })
            except Exception as e:
                failed += 1
                log.error("orchestrated_subtask_failed", subtask_id=sub_task.task_id, error=str(e))
                results.append({
                    "subtask_id": sub_task.task_id,
                    "agent_type": sub_agent_type.value,
                    "status": TaskStatus.FAILED.value,
                    "error": str(e),
                })
                if not continue_on_error:
                    break

        return {
            "status": "completed" if failed == 0 else "completed_with_errors",
            "subtasks_total": len(subtasks_payloads),
            "subtasks_succeeded": succeeded,
            "subtasks_failed": failed,
            "orchestrated_results": results,
        }

# Global Instance
orchestrator = AgentOrchestrator()
