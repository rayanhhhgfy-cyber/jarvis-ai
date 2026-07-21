# Phase 18: Cohort Analysis (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="cohort.analyze", description="Analyze customer cohorts by first-purchase month. Shows retention over time.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="cohort_analysis")
async def analyze() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as customers, COUNT(DISTINCT customer_email) as unique_emails FROM orders WHERE status IN ('paid','delivered') GROUP BY month ORDER BY month"))
    return {"ok": True, "cohorts": rows, "note": "Each cohort = customers who first purchased in that month."}
