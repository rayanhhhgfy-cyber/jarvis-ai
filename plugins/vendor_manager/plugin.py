# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="vendor.add", description="Add a supplier/vendor.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business")
async def _vendor_add() -> Dict[str, Any]:
    return {"ok": True, "plugin": "vendor_manager", "tool": "vendor.add"}

@tool(name="vendor.reorder_check", description="Check which products need reordering.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business")
async def _vendor_reorder_check() -> Dict[str, Any]:
    return {"ok": True, "plugin": "vendor_manager", "tool": "vendor.reorder_check"}

PLUGIN_NAME = "vendor_manager"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Add a supplier/vendor."