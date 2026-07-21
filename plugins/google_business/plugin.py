# Phase 18: Google My Business (REAL - guide + API where possible)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="gmb.update", description="Guide + API for updating Google My Business listing.", parameters={"type":"object","properties":{"business_name":{"type":"string"},"action":{"type":"string","default":"info","enum":["info","hours","photos","posts"]}},"required":["business_name"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="google_business")
async def gmb_update(business_name: str, action: str = "info") -> Dict[str, Any]:
    return {"ok": True, "business": business_name, "action": action, "manual_url": "https://business.google.com/dashboard", "note": "Google My Business API requires OAuth + verification. Use manual dashboard for now.", "instructions": f"1. Go to business.google.com 2. Select {business_name} 3. Update {action} 4. Save"}

@tool(name="gmb.reply_review", description="Generate an Arabic reply to a Google review.", parameters={"type":"object","properties":{"review_text":{"type":"string"},"rating":{"type":"integer","default":5}},"required":["review_text"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="google_business")
async def reply_review(review_text: str, rating: int = 5) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        tone = "thankful and warm" if rating >= 4 else "apologetic and solution-focused"
        reply = await llm_service.get_response(user_message=f"Review ({rating} stars): {review_text}", system_instructions=f"Write a {tone} reply in Arabic. Under 100 words. Professional.", inject_memory=False)
        return {"ok": True, "suggested_reply": reply.strip(), "rating": rating}
    except Exception as e: return {"ok": False, "error": str(e)}
