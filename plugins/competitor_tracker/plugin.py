# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="competitor.diff", description="Diff a competitor's website vs last check.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _competitor_diff() -> Dict[str, Any]:
    return {"ok": True, "plugin": "competitor_tracker", "tool": "competitor.diff"}

@tool(name="competitor.add", description="Add a competitor URL to track.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _competitor_add() -> Dict[str, Any]:
    return {"ok": True, "plugin": "competitor_tracker", "tool": "competitor.add"}

PLUGIN_NAME = "competitor_tracker"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Diff a competitor's website vs last check."