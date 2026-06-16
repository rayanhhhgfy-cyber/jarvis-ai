# ====================================================================
# JARVIS OMEGA — Health Agent
# ====================================================================
"""
Specialized Health Agent responsible for tracking vitals, fitness goals,
meal planning, and wellness reminders.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_health")

class AgentHealth:
    """
    Personal health and wellness agent. Tracks workouts and nutrition.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_health"
        self.agent_type = AgentType.WORKER
        try:
            self.agent_type = AgentType.HEALTH
        except AttributeError:
            pass

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("health_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "daily_summary")

            if action == "daily_summary":
                result_data = await self._get_daily_summary(task)
            elif action == "log_workout":
                result_data = await self._log_workout(task)
            elif action == "meal_plan":
                result_data = await self._generate_meal_plan(task)
            else:
                raise ValueError(f"Unknown Health action: {action}")

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
            log.error("health_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _get_daily_summary(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "steps": 8500,
            "calories_burned": 2100,
            "sleep_quality": "Good (7.5h)",
            "water_intake": "2.0L",
            "heart_rate_avg": "65 bpm"
        }

    async def _log_workout(self, task: TaskDefinition) -> Dict[str, Any]:
        workout_type = task.payload.get("workout_type", "Strength")
        duration = task.payload.get("duration", 45)
        return {
            "status": "success",
            "workout": workout_type,
            "duration_min": duration,
            "calories_estimated": 400,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _generate_meal_plan(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "breakfast": "Oatmeal with blueberries and walnuts",
            "lunch": "Grilled chicken salad with avocado",
            "dinner": "Baked salmon with quinoa and steamed broccoli",
            "snacks": ["Apple", "Greek yogurt"],
            "total_calories": 2200,
            "macros": {"P": "150g", "C": "200g", "F": "70g"}
        }
