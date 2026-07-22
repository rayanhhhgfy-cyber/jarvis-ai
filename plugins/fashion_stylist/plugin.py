# Phase 19: AI Fashion Stylist (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="fashion.suggest_outfit", description="Suggest an outfit for an occasion based on available items.", parameters={"type":"object","properties":{"occasion":{"type":"string","default":"casual","enum":["casual","business","formal","date","interview"]},"season":{"type":"string","default":"summer","enum":["spring","summer","autumn","winter"]},"available_items":{"type":"array","items":{"type":"string"},"default":[]}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="fashion_stylist")
async def suggest_outfit(occasion: str = "casual", season: str = "summer", available_items: list = None) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(user_message=f"Occasion: {occasion}, Season: {season}, Available: {available_items or 'general wardrobe'}", system_instructions="You are a personal stylist. Suggest a complete outfit in Arabic. Include: top, bottom, shoes, accessories. Consider the occasion and season. Be specific.", inject_memory=False)
        return {"ok": True, "outfit": reply.strip(), "occasion": occasion}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="fashion.shop_list", description="Generate a shopping list to complete a wardrobe.", parameters={"type":"object","properties":{"current_items":{"type":"array","items":{"type":"string"},"default":[]},"target_style":{"type":"string","default":"smart casual"}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="fashion_stylist")
async def shop_list(current_items: list = None, target_style: str = "smart casual") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(user_message=f"Current: {current_items}, Target: {target_style}", system_instructions="List 10 essential items missing from this wardrobe to achieve the target style. Output as a shopping list. Arabic.", inject_memory=False)
        return {"ok": True, "shopping_list": reply.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "fashion_stylist"; PLUGIN_VERSION = "1.0.0"
