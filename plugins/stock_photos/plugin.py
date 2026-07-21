# Phase 18: Stock Photo Seller (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="stock.generate", description="Generate + auto-tag stock photos for upload to Shutterstock/Adobe Stock.", parameters={"type":"object","properties":{"prompt":{"type":"string"},"count":{"type":"integer","default":5}},"required":["prompt"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="stock_photos")
async def generate(prompt: str, count: int = 5) -> Dict[str, Any]:
    from plugins.media_free.plugin import media_image_pollinations
    from backend.services.llm_service import llm_service
    photos = []
    variations = [prompt, f"{prompt} wide angle", f"{prompt} close up", f"{prompt} minimal", f"{prompt} dramatic lighting"]
    for i in range(min(count, len(variations))):
        img = await media_image_pollinations(prompt=variations[i], width=1920, height=1080)
        if img.get("ok"):
            # Auto-generate tags
            try:
                tag_reply = await llm_service.get_response(user_message=f"Image prompt: {variations[i]}", system_instructions="Generate 10 stock photo tags (single words). Output JSON: {tags: [string]}", inject_memory=False)
                import json
                tags = json.loads(tag_reply.strip().lstrip("`").rstrip("`").replace("json","",1) if tag_reply.strip().startswith("```") else tag_reply).get("tags",[])
            except: tags = []
            photos.append({"prompt": variations[i], "tags": tags, "generated": True})
    return {"ok": True, "photos": photos, "count": len(photos)}

@tool(name="stock.upload_guide", description="Guide for uploading to stock photo platforms.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="stock_photos")
async def upload_guide() -> Dict[str, Any]:
    return {"ok": True, "platforms": [{"name":"Shutterstock","url":"https://contributor.shutterstock.com","earnings":"$0.25-3 per download"},{"name":"Adobe Stock","url":"https://contributor.stock.adobe.com","earnings":"33% commission"},{"name":"Pixabay","url":"https://pixabay.com","earnings":"free exposure (no direct pay)"}]}
