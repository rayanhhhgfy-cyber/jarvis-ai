# Phase 18: Property Management (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="prop.collect_rent", description="Record rent collection from a tenant via Zain Cash.", parameters={"type":"object","properties":{"tenant_name":{"type":"string"},"amount_jod":{"type":"number"},"property_address":{"type":"string","default":""}},"required":["tenant_name","amount_jod"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="property_management")
async def collect_rent(tenant_name: str, amount_jod: float, property_address: str = "") -> Dict[str, Any]:
    business_db.audit("rent_collected", "property_management", target=tenant_name, details={"amount": amount_jod, "address": property_address})
    return {"ok": True, "tenant": tenant_name, "amount_jod": amount_jod, "note": "Rent recorded. Generate Zain Cash QR for collection."}

@tool(name="prop.maintenance", description="Log a maintenance request.", parameters={"type":"object","properties":{"property_address":{"type":"string"},"issue":{"type":"string"},"priority":{"type":"string","default":"normal","enum":["low","normal","high","urgent"]}},"required":["property_address","issue"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="property_management")
async def maintenance(property_address: str, issue: str, priority: str = "normal") -> Dict[str, Any]:
    business_db.audit("maintenance_request", "property_management", target=property_address, details={"issue": issue, "priority": priority})
    return {"ok": True, "property": property_address, "issue": issue, "priority": priority}
