# ====================================================================
# JARVIS OMEGA — Planner Agent
# ====================================================================
"""
Specialized Planner Agent responsible for breaking down high-level user tasks
into organized dependency graphs, ordering steps, and plotting pipelines.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_planner")

class AgentPlanner:
    """
    Project planner agent. Decomposes master user commands into structured
    subtasks and designs the execution sequence.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_planner"
        self.agent_type = AgentType.PLANNER

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes planning commands like task scheduling and step decomposition."""
        log.info("planner_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "decompose")

            if action == "decompose" or action == "plan":
                result_data = await self._decompose_goals(task)
            else:
                raise ValueError(f"Unknown Planner action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("planner_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _decompose_goals(self, task: TaskDefinition) -> Dict[str, Any]:
        """Breaks a composite goal down into concrete execution subtasks."""
        goal = task.payload.get("goal")
        if not goal:
            raise ValueError("goal description is required for decomposition")

        log.info("planning_decomposition_steps", goal=goal)
        
        # Static smart parser matching typical code builds or operations
        steps = [
            {
                "title": "Analyze and audit",
                "description": f"Gather prerequisites for goal: {goal}",
                "agent_type": "research",
                "payload": {"topic": goal}
            },
            {
                "title": "Write source files",
                "description": "Generate implementation code blocks.",
                "agent_type": "code",
                "payload": {"action": "write"}
            },
            {
                "title": "Verify code changes",
                "description": "Run local syntax compile tests.",
                "agent_type": "testing",
                "payload": {"action": "run"}
            }
        ]

        return {
            "master_goal": goal,
            "steps_count": len(steps),
            "subtasks": steps,
            "ordered": True
        }
