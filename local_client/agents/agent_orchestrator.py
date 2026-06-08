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
        self.agent_pool: Dict[str, Dict[str, Any]] = {}
        self.cpu_limit: float = 85.0
        self.mem_limit: float = 90.0

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
        
        # 1. Resource budgeting check
        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            if cpu > self.cpu_limit or mem > self.mem_limit:
                log.warning("resource_limit_exceeded_before_spawn", cpu=cpu, mem=mem)
                # Yield control to allow resources to settle
                await asyncio.sleep(1.0)
                cpu = psutil.cpu_percent()
                if cpu > self.cpu_limit or mem > self.mem_limit:
                    raise RuntimeError(f"Resource budget exceeded: CPU={cpu}%, MEM={mem}%")
        except Exception as e:
            log.debug("resource_check_failed", error=str(e))

        # 2. Trigger auto-cleanup for idle pool agents
        self._cleanup_idle_agents()

        # Spawn record in local registry
        agent_info = AgentInfo(
            agent_type=agent_type,
            parent_id=self.agent_id,
            status=AgentStatus.RUNNING,
            current_task_description=task.description
        )
        self.sub_agents[agent_info.agent_id] = agent_info

        try:
            # 3. Check warm agent pool
            pool_key = agent_type.value
            agent_instance = None
            if pool_key in self.agent_pool:
                log.info("retrieved_agent_from_warm_pool", agent_type=pool_key)
                entry = self.agent_pool[pool_key]
                agent_instance = entry["instance"]
                entry["last_used"] = time.time()
            else:
                # Dynamically import and instantiate the agent
                try:
                    module_name = f"local_client.agents.agent_{agent_type.value}"
                    class_name = f"Agent{agent_type.value.capitalize()}"
                    
                    import importlib
                    module = importlib.import_module(module_name)
                    agent_class = getattr(module, class_name)
                    agent_instance = agent_class()
                except (ImportError, AttributeError):
                    # 4. Fallback Dynamic Spawner: Spawns a generic MicroAgent for custom runtime requests
                    log.warning("agent_module_not_found_spawning_dynamic_microagent", agent_type=pool_key)
                    agent_instance = DynamicMicroAgent(pool_key)

                # Add to warm pool
                self.agent_pool[pool_key] = {
                    "instance": agent_instance,
                    "last_used": time.time()
                }

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

    def _cleanup_idle_agents(self) -> None:
        """Terminate and clean up warm pool agents idle for more than 300 seconds."""
        now = time.time()
        idle_timeout = 300.0
        expired_keys = []
        for key, entry in self.agent_pool.items():
            if now - entry["last_used"] > idle_timeout:
                expired_keys.append(key)
        
        for key in expired_keys:
            log.info("cleaning_up_idle_pool_agent", agent_type=key)
            del self.agent_pool[key]

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


class DynamicMicroAgent:
    """Fallback micro-agent spawned dynamically when no specialized module is found on disk."""
    
    def __init__(self, agent_type_str: str) -> None:
        self.agent_type_str = agent_type_str

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("dynamic_microagent_running_task", agent_type=self.agent_type_str, task_id=task.task_id)
        start_time = time.time()
        try:
            from backend.services.llm_service import llm_service
            import json
            import re
            
            system_prompt = (
                f"You are a specialized dynamic micro-agent: 'Agent{self.agent_type_str.capitalize()}'. "
                "Sir has requested you execute a task. Output a valid JSON result describing your findings or actions.\n"
                "Return ONLY a JSON object: {\"success\": true/false, \"message\": \"...\", \"result_data\": {...}}"
            )
            
            user_prompt = (
                f"Task Title: {task.title}\n"
                f"Task Description: {task.description}\n"
                f"Task Payload: {json.dumps(task.payload)}"
            )

            # Let LLM solve the dynamic execution
            response = await llm_service.get_response(
                user_message=user_prompt,
                system_instructions=system_prompt,
                inject_memory=False,
            )
            
            # Parse response
            clean = response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\n", "", clean)
                clean = re.sub(r"\n```$", "", clean)
                
            data = json.loads(clean.strip())
            
            elapsed = (time.time() - start_time) * 1000
            
            return TaskResult(
                task_id=task.task_id,
                agent_id=f"dynamic_{self.agent_type_str}",
                status=TaskStatus.COMPLETED if data.get("success", True) else TaskStatus.FAILED,
                result=data.get("result_data", data),
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=f"dynamic_{self.agent_type_str}",
                status=TaskStatus.FAILED,
                error=str(e),
                execution_time=elapsed,
            )


# Global Instance
orchestrator = AgentOrchestrator()
