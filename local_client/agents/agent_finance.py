# ====================================================================
# JARVIS OMEGA — Finance Agent
# ====================================================================
"""
Specialized Finance Agent responsible for tracking markets, managing portfolios,
analyzing crypto trends, and personal budget management.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_finance")

class AgentFinance:
    """
    Financial intelligence agent. Tracks stocks, crypto, and manages budgets using LLM and tools.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_finance"
        self.agent_type = AgentType.FINANCE

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("finance_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "market_analysis")

            if action == "market_analysis":
                result_data = await self._analyze_market(task)
            elif action == "track_portfolio":
                result_data = await self._track_portfolio(task)
            elif action == "budget_report":
                result_data = await self._generate_budget_report(task)
            else:
                # Fallback to general financial analysis
                result_data = await self._analyze_market(task)

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
            log.error("finance_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _analyze_market(self, task: TaskDefinition) -> Dict[str, Any]:
        query = task.payload.get("query") or "Global market summary"
        from backend.services.llm_service import LLMService
        llm = LLMService()

        analysis = await llm.get_response(
            user_message=f"Provide a detailed financial market analysis for: {query}",
            system_instructions="You are a senior financial analyst. Use real-time data if available via web search triggers."
        )
        return {
            "query": query,
            "analysis": analysis,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _track_portfolio(self, task: TaskDefinition) -> Dict[str, Any]:
        portfolio = task.payload.get("portfolio", [])
        from backend.services.llm_service import LLMService
        llm = LLMService()

        analysis = await llm.get_response(
            user_message=f"Analyze the performance and risk of this portfolio: {portfolio}",
            system_instructions="You are a portfolio manager. Provide actionable insights."
        )
        return {
            "portfolio": portfolio,
            "analysis": analysis,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _generate_budget_report(self, task: TaskDefinition) -> Dict[str, Any]:
        from backend.services.llm_service import LLMService
        llm = LLMService()

        report = await llm.get_response(
            user_message="Generate a comprehensive personal budget report and optimization plan.",
            system_instructions="You are a personal finance advisor. Focus on saving and smart investing."
        )
        return {
            "report": report,
            "timestamp": datetime.utcnow().isoformat()
        }
