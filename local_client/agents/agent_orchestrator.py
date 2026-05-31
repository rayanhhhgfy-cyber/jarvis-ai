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

    async def _delegate_to_agent(self, agent_type: AgentType, task: TaskDefinition) -> Dict[str, Any]:
        """Dynamically loads and delegates a task to a specialized agent."""
        log.info("delegating_task", agent_type=agent_type.value, task_id=task.task_id)
        
        # Spawn record in local registry
        agent_info = AgentInfo(
            agent_type=agent_type,
            parent_id=self.agent_id,
            status=AgentStatus.RUNNING,
            current_task_description=task.description
        )
        self.sub_agents[agent_info.agent_id] = agent_info

        try:
            # Dynamically import and execute the agent
            module_name = f"local_client.agents.agent_{agent_type.value}"
            class_name = f"Agent{agent_type.value.capitalize()}"
            
            # Special case for folder names or mapping
            import importlib
            module = importlib.import_module(module_name)
            agent_class = getattr(module, class_name)
            agent_instance = agent_class()

            # Execute
            task.assigned_agent_id = agent_info.agent_id
            result: TaskResult = await agent_instance.execute_task(task)
            
            agent_info.status = AgentStatus.COMPLETED if result.status == TaskStatus.COMPLETED else AgentStatus.FAILED
            agent_info.updated_at = datetime.utcnow()
            
            if result.status == TaskStatus.FAILED:
                raise RuntimeError(f"Sub-agent execution failed: {result.error}")

            return result.result or {}
            
        except Exception as e:
            agent_info.status = AgentStatus.FAILED
            agent_info.error = str(e)
            agent_info.updated_at = datetime.utcnow()
            raise

    async def _decompose_and_run(self, task: TaskDefinition) -> Dict[str, Any]:
        """Decomposes a complex task into multiple subtasks and runs them sequentially."""
        subtasks_payloads = task.payload.get("subtasks", [])
        if not subtasks_payloads:
            # Default fallback decomposition if none supplied
            log.warning("no_subtasks_found_in_orchestration_task", task_id=task.task_id)
            return {"status": "no_steps_to_orchestrate"}

        results = []
        for index, sub_payload in enumerate(subtasks_payloads):
            sub_agent_type = AgentType(sub_payload.get("agent_type", "os"))
            sub_task = TaskDefinition(
                title=sub_payload.get("title", f"Subtask {index}"),
                description=sub_payload.get("description", ""),
                agent_type=sub_agent_type,
                parent_task_id=task.task_id,
                payload=sub_payload.get("payload", {})
            )
            
            task.subtasks.append(sub_task.task_id)
            log.info("running_orchestrated_subtask", parent_id=task.task_id, subtask_id=sub_task.task_id)
            
            sub_result = await self._delegate_to_agent(sub_agent_type, sub_task)
            results.append({
                "subtask_id": sub_task.task_id,
                "agent_type": sub_agent_type.value,
                "result": sub_result
            })

        return {"orchestrated_results": results}

# Global Instance
orchestrator = AgentOrchestrator()
