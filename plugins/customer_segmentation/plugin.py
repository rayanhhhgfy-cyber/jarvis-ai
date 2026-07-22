# Phase 19: Customer Segmentation (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="segment.auto", description="Automatically segment customers by purchase behavior into VIP / Regular / At-risk / New.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="customer_segmentation")
async def auto() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT customer_name, COUNT(*) as orders, SUM(total) as spent, MIN(created_at) as first_order, MAX(created_at) as last_order FROM orders WHERE status IN ('paid','delivered') GROUP BY customer_name"))
    segments = {"VIP": [], "Regular": [], "At_Risk": [], "New": []}
    for r in rows:
        spent = r["spent"] or 0; orders = r["orders"]
        if spent > 500 or orders > 10: segments["VIP"].append(r)
        elif orders > 3: segments["Regular"].append(r)
        elif orders == 1: segments["New"].append(r)
        else: segments["At_Risk"].append(r)
    return {"ok": True, "total_customers": len(rows), "segments": {k: len(v) for k,v in segments.items()}, "details": {k: v[:5] for k,v in segments.items()}}

@tool(name="segment.target_campaign", description="Generate a targeted campaign message for a specific segment.", parameters={"type":"object","properties":{"segment":{"type":"string","enum":["VIP","Regular","At_Risk","New"]},"offer":{"type":"string","default":""}},"required":["segment"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="customer_segmentation")
async def target_campaign(segment: str, offer: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    templates = {"VIP": "شكراً لولائكم! لكم خصم خاص 25%", "Regular": "نفتقدكم! إليكم خصم 15% على طلبكم القادم", "At_Risk": "محتاجين نراكم مجدداً — خصم 30% لفترة محدودة", "New": "أهلاً بكم! استمتعوا بخصم 10% على أول طلب"}
    msg = offer or templates.get(segment, "")
    return {"ok": True, "segment": segment, "campaign_message": msg, "note": f"Send via marketing.post to all {segment} customers."}

PLUGIN_NAME = "customer_segmentation"; PLUGIN_VERSION = "1.0.0"
