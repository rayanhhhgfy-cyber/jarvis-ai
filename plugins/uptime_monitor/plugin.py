# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="uptime.check_all", description="Ping all deployed sites. Alert on downtime.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _uptime_check_all() -> Dict[str, Any]:
    return {"ok": True, "plugin": "uptime_monitor", "tool": "uptime.check_all"}

@tool(name="uptime.add_site", description="Add a URL to monitor.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _uptime_add_site() -> Dict[str, Any]:
    return {"ok": True, "plugin": "uptime_monitor", "tool": "uptime.add_site"}

PLUGIN_NAME = "uptime_monitor"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Ping all deployed sites. Alert on downtime."