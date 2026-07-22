# Phase 19: Ad Copy Generator (REAL)
from __future__ import annotations
import json
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="adcopy.generate", description="Generate high-converting ad copy for Meta/Google/TikTok ads in Arabic.", parameters={"type":"object","properties":{"product":{"type":"string"},"platform":{"type":"string","default":"meta","enum":["meta","google","tiktok","snapchat"]},"audience":{"type":"string","default":"general"},"cta":{"type":"string","default":"shop_now"}},"required":["product"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="ad_copy")
async def generate(product: str, platform: str = "meta", audience: str = "general", cta: str = "shop_now") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    platform_specs = {"meta": "Facebook + Instagram ad. Headline (40 chars) + body (125 chars) + CTA.", "google": "Google Search ad. 3 headlines (30 chars each) + 2 descriptions (90 chars).", "tiktok": "TikTok ad. Short hook + value prop. Under 100 chars.", "snapchat": "Snapchat ad. Top snap text + headline. Under 250 chars."}
    try:
        reply = await llm_service.get_response(user_message=f"Product: {product}, Audience: {audience}, CTA: {cta}", system_instructions=f"Write Arabic ad copy for {platform}. Format: {platform_specs.get(platform,'')}. Output STRICT JSON: {{headline:string, body:string, cta_text:string}}", inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        return {"ok": True, "platform": platform, **json.loads(text)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="adcopy.variations", description="Generate 5 ad copy variations for A/B testing.", parameters={"type":"object","properties":{"product":{"type":"string"},"platform":{"type":"string","default":"meta"}},"required":["product"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="ad_copy")
async def variations(product: str, platform: str = "meta") -> Dict[str, Any]:
    results = []
    hooks = ["curiosity","urgency","social_proof","benefit","question"]
    for hook in hooks:
        r = await generate(product=product, platform=platform)
        if r.get("ok"): r["hook_type"] = hook; results.append(r)
    return {"ok": True, "variations": results, "count": len(results)}

PLUGIN_NAME = "ad_copy"; PLUGIN_VERSION = "1.0.0"
