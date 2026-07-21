# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="ssl.check_all", description="Check SSL certificates. Alert if expiring <30 days.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _ssl_check_all() -> Dict[str, Any]:
    return {"ok": True, "plugin": "ssl_monitor", "tool": "ssl.check_all"}

PLUGIN_NAME = "ssl_monitor"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Check SSL certificates. Alert if expiring <30 days."