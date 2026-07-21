# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="habit.add", description="Add a daily habit to track.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="personal")
async def _habit_add() -> Dict[str, Any]:
    return {"ok": True, "plugin": "habit_tracker", "tool": "habit.add"}

@tool(name="habit.check", description="Mark habit as done for today.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="personal")
async def _habit_check() -> Dict[str, Any]:
    return {"ok": True, "plugin": "habit_tracker", "tool": "habit.check"}

PLUGIN_NAME = "habit_tracker"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Add a daily habit to track."