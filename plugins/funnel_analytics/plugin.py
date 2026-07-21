# Phase 18: Funnel Analytics (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="funnel.analyze", description="Sales funnel: how many prospects at each stage + drop-off rates.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="funnel_analytics")
async def analyze() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT status, COUNT(*) as n FROM sales_conversations GROUP BY status ORDER BY CASE status WHEN 'pitching' THEN 1 WHEN 'pitched' THEN 2 WHEN 'in_conversation' THEN 3 WHEN 'closing' THEN 4 WHEN 'deal_closed' THEN 5 WHEN 'pitch_failed' THEN 6 ELSE 7 END"))
    total = sum(r["n"] for r in rows)
    stages = []
    prev = total
    for r in rows:
        drop = round((1 - r["n"]/prev) * 100, 1) if prev else 0
        stages.append({"stage": r["status"], "count": r["n"], "pct_of_total": round(r["n"]/total*100,1) if total else 0, "drop_off_pct": drop})
        prev = r["n"]
    return {"ok": True, "total_conversations": total, "funnel": stages}
