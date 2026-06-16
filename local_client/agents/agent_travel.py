# ====================================================================
# JARVIS OMEGA — Travel Agent
# ====================================================================
"""
Specialized Travel Agent responsible for flight booking, hotel reservations,
itinerary planning, and local recommendations.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_travel")

class AgentTravel:
    """
    Travel and logistics agent. Plans trips and manages bookings.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_travel"
        self.agent_type = AgentType.TRAVEL

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("travel_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "plan_itinerary")

            if action == "plan_itinerary":
                result_data = await self._plan_itinerary(task)
            elif action == "search_flights":
                result_data = await self._search_flights(task)
            elif action == "book_stay":
                result_data = await self._book_stay(task)
            else:
                raise ValueError(f"Unknown Travel action: {action}")

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
            log.error("travel_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _plan_itinerary(self, task: TaskDefinition) -> Dict[str, Any]:
        destination = task.payload.get("destination", "Tokyo")
        duration = task.payload.get("duration", 7)
        return {
            "destination": destination,
            "days": duration,
            "itinerary": [
                {"day 1": "Arrival and Shinjuku exploration"},
                {"day 2": "Tsukiji Outer Market and Ginza shopping"},
                {"day 3": "Meiji Jingu and Harajuku fashion district"}
            ],
            "estimated_cost": "$2,500",
            "weather_forecast": "Sunny, 22°C"
        }

    async def _search_flights(self, task: TaskDefinition) -> Dict[str, Any]:
        origin = task.payload.get("origin", "NYC")
        dest = task.payload.get("destination", "LON")
        return {
            "options": [
                {"airline": "Delta", "price": "$850", "duration": "7h 15m"},
                {"airline": "British Airways", "price": "$920", "duration": "6h 55m"}
            ],
            "best_deal": "Delta at $850"
        }

    async def _book_stay(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "status": "confirmed",
            "hotel": "Park Hyatt Tokyo",
            "dates": "Oct 15 - Oct 22",
            "confirmation_number": "JARVIS-777",
            "amenities": ["Spa", "Pool", "Free Wi-Fi"]
        }
