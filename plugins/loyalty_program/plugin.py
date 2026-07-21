# Phase 18: Loyalty Program (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="loyalty.add_points", description="Add loyalty points to a customer.", parameters={"type":"object","properties":{"customer_name":{"type":"string"},"points":{"type":"integer"},"reason":{"type":"string","default":"purchase"}},"required":["customer_name","points"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="loyalty_program")
async def add_points(customer_name: str, points: int, reason: str = "purchase") -> Dict[str, Any]:
    business_db.audit("loyalty_points", "loyalty", target=customer_name, details={"points": points, "reason": reason})
    return {"ok": True, "customer": customer_name, "points_added": points}

@tool(name="loyalty.check_balance", description="Check a customer's total loyalty points.", parameters={"type":"object","properties":{"customer_name":{"type":"string"}},"required":["customer_name"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="loyalty_program")
async def check_balance(customer_name: str) -> Dict[str, Any]:
    try:
        rows = business_db.query("SELECT details FROM audit_log WHERE action = 'loyalty_points' AND target = ?", (customer_name,))
        total = 0
        for r in rows:
            import json
            d = json.loads(r["details"] or "{}")
            total += d.get("points", 0)
        tier = "Bronze" if total < 100 else "Silver" if total < 500 else "Gold" if total < 1000 else "Platinum"
        return {"ok": True, "customer": customer_name, "total_points": total, "tier": tier}
    except Exception as e:
        return {"ok": False, "error": str(e)}
