# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="loyalty.add_points", description="Add loyalty points to a customer.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business")
async def _loyalty_add_points() -> Dict[str, Any]:
    return {"ok": True, "plugin": "loyalty_program", "tool": "loyalty.add_points"}

@tool(name="loyalty.check_balance", description="Check customer's loyalty points balance.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business")
async def _loyalty_check_balance() -> Dict[str, Any]:
    return {"ok": True, "plugin": "loyalty_program", "tool": "loyalty.check_balance"}

PLUGIN_NAME = "loyalty_program"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Add loyalty points to a customer."