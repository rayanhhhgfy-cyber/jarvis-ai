# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="webhook.register", description="Register a webhook endpoint JARVIS will listen on.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="integration")
async def _webhook_register() -> Dict[str, Any]:
    return {"ok": True, "plugin": "webhook_receiver", "tool": "webhook.register"}

PLUGIN_NAME = "webhook_receiver"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Register a webhook endpoint JARVIS will listen on."