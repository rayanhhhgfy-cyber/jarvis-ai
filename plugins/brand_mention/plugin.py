# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="mentions.scan", description="Scan web + social for brand mentions.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="monitoring")
async def _mentions_scan() -> Dict[str, Any]:
    return {"ok": True, "plugin": "brand_mention", "tool": "mentions.scan"}

PLUGIN_NAME = "brand_mention"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Scan web + social for brand mentions."