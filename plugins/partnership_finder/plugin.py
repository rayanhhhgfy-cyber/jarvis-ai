# Phase 19: Partnership Finder (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="partner.find", description="Find complementary businesses for cross-promotion partnerships.", parameters={"type":"object","properties":{"your_niche":{"type":"string"},"location":{"type":"string","default":"Amman, Jordan"}},"required":["your_niche"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="partnership_finder")
async def find(your_niche: str, location: str = "Amman, Jordan") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(user_message=f"My niche: {your_niche}, Location: {location}", system_instructions='Suggest 5 complementary business types that would make good cross-promotion partners. Output STRICT JSON: {partners:[{type:string, why:string, cross_promo_idea:string}]}.', inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        import json
        return {"ok": True, **json.loads(text)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="partner.pitch", description="Write a cross-promotion pitch for a partner business.", parameters={"type":"object","properties":{"partner_type":{"type":"string"},"your_business":{"type":"string"}},"required":["partner_type","your_business"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="partnership_finder")
async def pitch(partner_type: str, your_business: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        msg = await llm_service.get_response(user_message=f"Partner: {partner_type}, My business: {your_business}", system_instructions="Write a short cross-promotion pitch in Jordanian Arabic. Propose a win-win collaboration. Under 150 words.", inject_memory=False)
        return {"ok": True, "pitch": msg.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "partnership_finder"; PLUGIN_VERSION = "1.0.0"
