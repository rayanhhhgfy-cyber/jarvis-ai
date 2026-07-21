# Phase 18: CLV Predictor (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="clv.predict", description="Predict customer lifetime value based on purchase history.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="clv_predictor")
async def predict() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT customer_name, customer_email, COUNT(*) as orders, SUM(total) as spent, MIN(created_at) as first_order, MAX(created_at) as last_order FROM orders WHERE status IN ('paid','delivered') GROUP BY customer_name ORDER BY spent DESC LIMIT 20"))
    results = []
    for r in rows:
        avg_order = r["spent"] / r["orders"] if r["orders"] else 0
        # Simple CLV: avg_order * 4 (assuming 4 purchases/year) * 3 (3 year retention)
        clv = avg_order * 4 * 3
        results.append({"customer": r["customer_name"], "email": r["customer_email"], "orders": r["orders"], "total_spent": round(r["spent"] or 0, 2), "avg_order": round(avg_order, 2), "predicted_clv_jod": round(clv, 2)})
    return {"ok": True, "top_customers": results, "note": "CLV = avg_order x 4 purchases/year x 3 years retention."}
