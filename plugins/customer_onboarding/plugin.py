# Phase 18: Customer Onboarding (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="onboarding.start", description="Start automated onboarding for a new customer: welcome email + tutorial + first-steps.", parameters={"type":"object","properties":{"customer_name":{"type":"string"},"customer_email":{"type":"string"},"product_name":{"type":"string","default":""}},"required":["customer_name","customer_email"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="customer_onboarding")
async def start(customer_name: str, customer_email: str, product_name: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        welcome = await llm_service.get_response(
            user_message=f"Customer: {customer_name}, Product: {product_name}",
            system_instructions="Write a warm Arabic welcome email for a new customer. Include: welcome, what they got, how to get started (3 steps), support contact. Markdown.",
            inject_memory=False)
        from plugins.communication.plugin import email_send
        await email_send(to=customer_email, subject=f"مرحباً بك {customer_name}! 🎉", body=welcome)
        business_db.audit("customer_onboarded", "customer_onboarding", target=customer_name, details={"email": customer_email})
        return {"ok": True, "customer": customer_name, "welcome_sent": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
