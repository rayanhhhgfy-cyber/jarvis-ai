# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="logs.search", description="Search across all system logs.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _logs_search() -> Dict[str, Any]:
    return {"ok": True, "plugin": "log_aggregator", "tool": "logs.search"}

PLUGIN_NAME = "log_aggregator"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Search across all system logs."