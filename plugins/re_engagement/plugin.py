# Phase 19: Auto Re-engagement (REAL)
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="reengage.find_inactive", description="Find customers who haven't ordered in 30/60/90 days.", parameters={"type":"object","properties":{"days_inactive":{"type":"integer","default":60}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="re_engagement")
async def find_inactive(days_inactive: int = 60) -> Dict[str, Any]:
    cutoff = (datetime.utcnow() - timedelta(days=days_inactive)).isoformat()
    rows = business_db.rows_to_dicts(business_db.query("SELECT customer_name, customer_phone, customer_email, MAX(created_at) as last_order FROM orders WHERE customer_name != '' GROUP BY customer_name HAVING last_order < ? LIMIT 50", (cutoff,)))
    return {"ok": True, "inactive_days": days_inactive, "inactive_customers": len(rows), "customers": rows}

@tool(name="reengage.send_offer", description="Generate + send a personalized win-back offer to inactive customers.", parameters={"type":"object","properties":{"customer_name":{"type":"string"},"channel":{"type":"string","default":"whatsapp","enum":["whatsapp","email"]},"discount_pct":{"type":"integer","default":15}},"required":["customer_name"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="re_engagement")
async def send_offer(customer_name: str, channel: str = "whatsapp", discount_pct: int = 15) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        msg = await llm_service.get_response(user_message=f"Customer: {customer_name}, Discount: {discount_pct}%", system_instructions=f"Write a warm win-back message in Jordanian Arabic. Offer {discount_pct}% discount on their next order. Short, personal, not pushy. Under 100 chars.", inject_memory=False)
        return {"ok": True, "message": msg.strip(), "channel": channel, "customer": customer_name, "note": "Use marketing.post to send this message."}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "re_engagement"; PLUGIN_VERSION = "1.0.0"
