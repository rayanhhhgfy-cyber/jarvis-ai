# ====================================================================
# JARVIS OMEGA — Education Agent (Academy)
# ====================================================================
"""
Specialized Education Agent.
Curates learning paths and generates 5-minute "Matrix-style" skill briefings.
"""

from __future__ import annotations

import time
from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger
from backend.services.llm_service import LLMService

log = get_logger("agent_education")

class AgentEducation:
    def __init__(self) -> None:
        self.agent_id = "agent_education"
        self.llm = LLMService()

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("education_agent_teaching")
        start_time = time.time()

        topic = task.payload.get("topic", "Quantum Computing")

        briefing = await self.llm.get_response(
            user_message=f"Create a 5-minute 'Matrix-style' briefing for Sir on: {topic}.",
            system_instructions="You are JARVIS. Be incredibly efficient. Use high-level analogies."
        )

        return TaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=TaskStatus.COMPLETED,
            result={"briefing": briefing, "status": "Ready for upload to neural cache"},
            execution_time=(time.time() - start_time) * 1000
        )
