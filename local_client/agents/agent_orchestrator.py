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
from shared.learning_loop import learning_loop
from local_client.hardware_scanner import hardware_scanner

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
        self.hardware_specs = hardware_scanner.scan()

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
            target_agent = task.agent_type
            
            if target_agent == AgentType.ORCHESTRATOR:
                result_data = await self._decompose_and_run(task)
            else:
                result_data = await self._run_subagent(target_agent, task)

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

    async def _run_subagent(self, agent_type: AgentType, task: TaskDefinition) -> Dict[str, Any]:
        """Wrapper around delegation to sub-agents with learning loop integration."""
        # Query lessons before acting
        lessons = learning_loop.query_lessons(task.description or task.title)
        if lessons:
            log.info("injecting_lesson_hint", task_id=task.task_id)
            task.payload["past_lesson_hint"] = lessons[0].get("solution")

        return await self._delegate_to_agent(agent_type, task)

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
                # Check for capability gap
                if any(gap in (result.error or "").lower() for gap in ["unknown action", "not implemented", "missing tool"]):
                    log.warning("capability_gap_detected", error=result.error)
                    # Suggest self-modification

                raise RuntimeError(f"Sub-agent execution failed: {result.error}")

            # Record success lesson
            learning_loop.remember_lesson(
                task_description=task.description or task.title,
                error_pattern="",
                root_cause="none",
                solution=str(result.result)[:500],
                success=True
            )

            return result.result or {}
            
        except Exception as e:
            agent_info.status = AgentStatus.FAILED
            agent_info.error = str(e)
            agent_info.updated_at = datetime.utcnow()

            # Record exception as failure lesson
            learning_loop.remember_lesson(
                task_description=task.description or task.title,
                error_pattern=str(e),
                root_cause="orchestrator_exception",
                solution="Investigate orchestrator logs and sub-agent stability.",
                success=False
            )

            raise

    async def _decompose_and_run(self, task: TaskDefinition) -> Dict[str, Any]:
        """Decomposes a complex task into multiple subtasks and runs them sequentially."""
        # Check for OMEGA Goal Management (Long-running autonomy)
        is_long_running = task.payload.get("long_running", False)
        if is_long_running:
            return await self._manage_long_running_goal(task)

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

    async def _manage_long_running_goal(self, task: TaskDefinition) -> Dict[str, Any]:
        """Executes a goal autonomously over a long duration with advanced error recovery."""
        log.info("initializing_long_running_omega_session", task_id=task.task_id, duration_limit="100h+")

        goal_description = task.description or task.title
        max_iterations = task.payload.get("max_iterations", 1000)
        iteration = 0
        results = []

        while iteration < max_iterations:
            iteration += 1
            log.info("omega_iteration", iteration=iteration, goal=goal_description)

            try:
                # 1. Self-Reflection & Planning
                from local_client.agents.agent_planner import AgentPlanner
                planner = AgentPlanner()
                plan_task = TaskDefinition(
                    title=f"Plan Iteration {iteration}",
                    description=f"Plan next steps for: {goal_description}",
                    agent_type=AgentType.PLANNER,
                    payload={"action": "decompose_goal", "goal": goal_description}
                )
                plan_result = await planner.execute_task(plan_task)
                next_steps = plan_result.result.get("phases", [])[0].get("tasks", []) if plan_result.status == TaskStatus.COMPLETED else []

                if not next_steps:
                    log.info("goal_accomplished_or_stalled", iteration=iteration)
                    break

                # 2. Execution of next steps
                for step in next_steps:
                    log.info("executing_omega_step", step=step)

                    # OMEGA logic: Dynamically determine the best agent for each step
                    # For now, we delegate to the Research agent to gather data for the step
                    sub_task = TaskDefinition(
                        title=f"Autonomous Step: {step}",
                        description=f"Executing OMEGA sub-step: {step}",
                        agent_type=AgentType.RESEARCH,
                        payload={"action": "deep_research", "topic": step}
                    )

                    # Record the intention in the learning loop
                    learning_loop.remember_lesson(
                        task_description=f"Executing {step} for goal {goal_description}",
                        error_pattern="",
                        root_cause="none",
                        solution="Executing via autonomous delegation",
                        success=True
                    )

                    await self._delegate_to_agent(AgentType.RESEARCH, sub_task)
                    await asyncio.sleep(1) # Intentional delay for stability

                results.append({"iteration": iteration, "status": "progressed"})

            except Exception as e:
                log.error("omega_iteration_failed_recovering", error=str(e))
                # Persistent Learning: Record mistake and figure out recovery
                learning_loop.remember_lesson(
                    task_description=f"Long running iteration {iteration}",
                    error_pattern=str(e),
                    root_cause="runtime_failure",
                    solution="Apply self-modification or retry with alternate agent.",
                    success=False
                )
                await asyncio.sleep(5) # Cooldown before recovery

        return {"status": "omega_session_complete", "iterations": iteration, "results": results}


# Global Instance
orchestrator = AgentOrchestrator()
