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
    Personal health and wellness agent. Tracks workouts and nutrition using LLM integration.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_health"
        self.agent_type = AgentType.HEALTH

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("health_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "wellness_plan")

            if action == "wellness_plan" or action == "daily_summary":
                result_data = await self._generate_wellness_plan(task)
            elif action == "analyze_vitals":
                result_data = await self._analyze_vitals(task)
            else:
                result_data = await self._generate_wellness_plan(task)

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

    async def _generate_wellness_plan(self, task: TaskDefinition) -> Dict[str, Any]:
        goals = task.payload.get("goals", "General fitness and longevity")
        from backend.services.llm_service import LLMService
        llm = LLMService()

        plan = await llm.get_response(
            user_message=f"Create a personalized wellness, nutrition, and workout plan for: {goals}",
            system_instructions="You are an elite health coach and nutritionist. Provide a detailed, science-based plan."
        )
        return {
            "goals": goals,
            "plan": plan,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _analyze_vitals(self, task: TaskDefinition) -> Dict[str, Any]:
        vitals = task.payload.get("vitals", {})
        from backend.services.llm_service import LLMService
        llm = LLMService()

        analysis = await llm.get_response(
            user_message=f"Analyze these health vitals and provide recommendations: {vitals}",
            system_instructions="You are a medical data analyst. Provide insights on trends and optimization."
        )
        return {
            "vitals": vitals,
            "analysis": analysis,
            "timestamp": datetime.utcnow().isoformat()
        }
