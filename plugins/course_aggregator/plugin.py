# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="course_agg.search", description="Search online course platforms for affiliate opportunities.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="affiliate")
async def _course_agg_search() -> Dict[str, Any]:
    return {"ok": True, "plugin": "course_aggregator", "tool": "course_agg.search"}

PLUGIN_NAME = "course_aggregator"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Search online course platforms for affiliate opportunities."