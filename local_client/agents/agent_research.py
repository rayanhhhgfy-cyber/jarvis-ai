# ====================================================================
# JARVIS OMEGA — Research Agent
# ====================================================================
"""
Specialized Research Agent responsible for deep dives into specific topics,
literature reviews, and trend analysis.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_research")

class AgentResearch:
    """
    Deep research agent. Synthesizes complex information from multiple sources using LLM.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_research"
        self.agent_type = AgentType.RESEARCH

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("research_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "deep_research")

            if action == "deep_research" or action == "compile" or action == "study":
                result_data = await self._perform_deep_research(task)
            elif action == "trend_analysis":
                result_data = await self._analyze_trends(task)
            elif action == "verify_facts":
                result_data = await self._verify_facts(task)
            else:
                raise ValueError(f"Unknown Research action: {action}")

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
            log.error("research_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _perform_deep_research(self, task: TaskDefinition) -> Dict[str, Any]:
        topic = task.payload.get("topic") or task.payload.get("query")
        if not topic:
            raise ValueError("topic is required for research")

        from backend.services.llm_service import LLMService
        llm = LLMService()

        system_instructions = (
            "You are the JARVIS Research Subsystem. "
            "Generate a highly structured, detailed technical research brief on the given topic. "
            "Use markdown. Include Executive Summary, Findings, and Technical Analysis."
        )

        brief = await llm.get_response(
            user_message=f"Deep research on: {topic}",
            system_instructions=system_instructions
        )

        return {
            "topic": topic,
            "briefing": brief,
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _analyze_trends(self, task: TaskDefinition) -> Dict[str, Any]:
        industry = task.payload.get("industry", "Technology")
        from backend.services.llm_service import LLMService
        llm = LLMService()

        brief = await llm.get_response(
            user_message=f"Analyze current and emerging trends in the {industry} industry.",
            system_instructions="You are a strategic trend analyst. Provide data-backed forecasts."
        )
        return {
            "industry": industry,
            "analysis": brief,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _verify_facts(self, task: TaskDefinition) -> Dict[str, Any]:
        statement = task.payload.get("statement")
        from backend.services.llm_service import LLMService
        llm = LLMService()

        brief = await llm.get_response(
            user_message=f"Verify the following statement and provide evidence: {statement}",
            system_instructions="You are a fact-checker. Be objective and cite sources if possible."
        )
        return {
            "statement": statement,
            "verification": brief,
            "timestamp": datetime.utcnow().isoformat()
        }
