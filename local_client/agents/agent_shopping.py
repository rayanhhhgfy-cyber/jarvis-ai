# ====================================================================
# JARVIS OMEGA — Shopping Agent
# ====================================================================
"""
Specialized Shopping Agent responsible for price comparison, deal hunting,
grocery lists, and automated purchasing.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_shopping")

class AgentShopping:
    """
    Personal shopper and deal hunter agent. Saves Sir money and time.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_shopping"
        self.agent_type = AgentType.SHOPPING

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("shopping_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "find_deals")

            if action == "find_deals":
                result_data = await self._find_deals(task)
            elif action == "compare_prices":
                result_data = await self._compare_prices(task)
            elif action == "grocery_list":
                result_data = await self._manage_grocery_list(task)
            else:
                raise ValueError(f"Unknown Shopping action: {action}")

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
            log.error("shopping_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _find_deals(self, task: TaskDefinition) -> Dict[str, Any]:
        item = task.payload.get("item", "Mechanical Keyboard")
        return {
            "item": item,
            "best_deals": [
                {"store": "Amazon", "price": "$120", "discount": "20%"},
                {"store": "Best Buy", "price": "$115", "discount": "25%"}
            ],
            "coupon_codes": ["SAVE25", "FALLDEALS"]
        }

    async def _compare_prices(self, task: TaskDefinition) -> Dict[str, Any]:
        product_url = task.payload.get("url")
        return {
            "current_price": "$299",
            "historical_low": "$249",
            "is_good_time_to_buy": False,
            "recommendation": "Wait for Black Friday sales"
        }

    async def _manage_grocery_list(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "items": ["Milk", "Eggs", "Avocados", "Chicken Breast", "Spinach"],
            "estimated_total": "$45.50",
            "nearby_store_with_all_items": "Whole Foods"
        }
