# Phase 18: Print-on-Demand (REAL)
from __future__ import annotations
import base64, io
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="pod.design", description="Generate a t-shirt/mug/poster design from a text prompt using Pollinations.", parameters={"type":"object","properties":{"prompt":{"type":"string"},"product_type":{"type":"string","default":"tshirt","enum":["tshirt","mug","poster","phone_case"]}},"required":["prompt"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="print_on_demand")
async def design(prompt: str, product_type: str = "tshirt") -> Dict[str, Any]:
    from plugins.media_free.plugin import media_image_pollinations
    r = await media_image_pollinations(prompt=f"{prompt}, minimalist design for {product_type}, transparent background style, high contrast", width=1024, height=1024)
    return r

@tool(name="pod.upload_guide", description="Guide for uploading designs to Redbubble + Teespring + Merch by Amazon.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="print_on_demand")
async def upload_guide() -> Dict[str, Any]:
    return {"ok": True, "platforms": [{"name":"Redbubble","url":"https://redbubble.com","signup":"free","royalty":"10-20% per sale"},{"name":"Teespring","url":"https://teespring.com","signup":"free","royalty":"you set the price"},{"name":"Merch by Amazon","url":"https://merch.amazon.com","signup":"invitation-only (apply)","royalty":"$2-7 per shirt"}]}
