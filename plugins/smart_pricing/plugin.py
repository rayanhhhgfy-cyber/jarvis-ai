# Phase 19: Smart Pricing Engine (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="pricing.analyze", description="Analyze current product prices vs sales velocity. Find overpriced/underpriced items.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="smart_pricing")
async def analyze() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT p.name, p.price, p.currency, COUNT(o.id) as orders FROM products p LEFT JOIN orders o ON p.id = o.product_id GROUP BY p.id ORDER BY orders DESC"))
    analysis = []
    for r in rows:
        status = "good" if r["orders"] > 5 else "overpriced_or_unknown" if r["orders"] == 0 else "low_demand"
        analysis.append({"product": r["name"], "price": r["price"], "currency": r["currency"], "orders": r["orders"], "status": status})
    return {"ok": True, "products_analyzed": len(analysis), "analysis": analysis}

@tool(name="pricing.recommend", description="Recommend price adjustments based on sales data.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="smart_pricing")
async def recommend() -> Dict[str, Any]:
    analysis = await analyze()
    if not analysis.get("ok"): return analysis
    recs = []
    for p in analysis["analysis"]:
        if p["status"] == "overpriced_or_unknown": recs.append({"product": p["product"], "action": "LOWER PRICE 10-20%", "reason": "Zero sales — price may be too high"})
        elif p["status"] == "low_demand": recs.append({"product": p["product"], "action": "TEST LOWER PRICE 5-10%", "reason": "Low demand — try price reduction"})
        else: recs.append({"product": p["product"], "action": "HOLD OR RAISE 5%", "reason": "Good demand — can experiment with higher price"})
    return {"ok": True, "recommendations": recs}

PLUGIN_NAME = "smart_pricing"; PLUGIN_VERSION = "1.0.0"
