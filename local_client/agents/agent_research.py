# ====================================================================
# JARVIS OMEGA — Research Agent
# ====================================================================
"""
Specialized Research Agent responsible for searching documentation,
fetching API schemas, and compiling research briefs for Sir.
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
    Research and technical study agent. Searches offline cached document files,
    indexes libraries, and summarizes API usage guides.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_research"
        self.agent_type = AgentType.RESEARCH

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes research tasks like summarizing documents or reviewing API guidelines."""
        log.info("research_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "compile")

            if action == "compile" or action == "study":
                result_data = await self._compile_research(task)
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

    async def _compile_research(self, task: TaskDefinition) -> Dict[str, Any]:
        """Compiles a structured markdown research document based on user topic."""
        topic = task.payload.get("topic")
        if not topic:
            raise ValueError("topic is required for research compile action")

        log.info("compiling_research_brief", topic=topic)
        
        # Import LLMService locally to avoid circular dependencies if any
        from backend.services.llm_service import LLMService
        llm = LLMService()
        
        system_instructions = (
            "You are the JARVIS Research Subsystem. "
            "Your objective is to generate highly structured, detailed, and accurate "
            "technical research briefs on a given topic. "
            "Use markdown heavily. Include an Executive Summary, Key Details/Findings, "
            "and any relevant Code Snippets or Technical Patterns if applicable."
        )
        
        user_msg = f"Compile a comprehensive research brief on the following topic: {topic}"
        
        # LLMService has built-in web search, so it will search if needed based on triggers!
        brief = await llm.get_response(
            user_message=user_msg,
            inject_memory=False,
            system_instructions=system_instructions
        )

        return {
            "topic": topic,
            "brief_length_chars": len(brief),
            "compiled_markdown": brief,
            "status": "completed"
        }
