# ====================================================================
# JARVIS OMEGA — Education Agent
# ====================================================================
"""
Specialized Education Agent responsible for tutoring, language learning,
creating study plans, and summarizing academic papers.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_education")

class AgentEducation:
    """
    Learning and tutoring agent. Helps Sir master new skills.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_education"
        self.agent_type = AgentType.EDUCATION

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("education_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "summarize_paper")

            if action == "summarize_paper":
                result_data = await self._summarize_paper(task)
            elif action == "language_lesson":
                result_data = await self._get_language_lesson(task)
            elif action == "study_plan":
                result_data = await self._create_study_plan(task)
            else:
                raise ValueError(f"Unknown Education action: {action}")

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
            log.error("education_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _summarize_paper(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "title": "Attention Is All You Need",
            "summary": "This seminal paper introduces the Transformer architecture...",
            "key_takeaways": [
                "Self-attention mechanism",
                "Parallelization in sequence modeling",
                "Replacement of RNNs/CNNs"
            ]
        }

    async def _get_language_lesson(self, task: TaskDefinition) -> Dict[str, Any]:
        lang = task.payload.get("language", "Arabic")
        return {
            "language": lang,
            "phrase_of_the_day": "Marhaban (مرحباً)",
            "meaning": "Hello",
            "context": "Universal greeting in the Arab world",
            "audio_available": True
        }

    async def _create_study_plan(self, task: TaskDefinition) -> Dict[str, Any]:
        topic = task.payload.get("topic", "Quantum Computing")
        return {
            "topic": topic,
            "duration": "4 weeks",
            "schedule": [
                {"week 1": "Linear Algebra and Qubits"},
                {"week 2": "Quantum Gates and Circuits"},
                {"week 3": "Shor's Algorithm and Grover's Algorithm"},
                {"week 4": "Quantum Error Correction"}
            ]
        }
