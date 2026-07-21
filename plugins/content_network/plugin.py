# Phase 18: Content Site Network
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="cn.build_site", description="Build an SEO niche content site: keyword -> landing + 5 articles -> deploy ready.", parameters={"type":"object","properties":{"keyword":{"type":"string"},"language":{"type":"string","default":"ar"}},"required":["keyword"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="content_network")
async def build_site(keyword: str, language: str = "ar") -> Dict[str, Any]:
    from plugins.website.plugin import website_generate_landing_page
    site = await website_generate_landing_page(product_name=keyword, tagline=f"Best {keyword} guide", language=language, rtl=(language=="ar"))
    return site

@tool(name="cn.generate_articles", description="Generate 5 SEO articles for a niche site.", parameters={"type":"object","properties":{"keyword":{"type":"string"},"count":{"type":"integer","default":5}},"required":["keyword"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="content_network")
async def generate_articles(keyword: str, count: int = 5) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    articles = []
    for i in range(count):
        try:
            art = await llm_service.get_response(user_message=f"Article {i+1} about: {keyword}", system_instructions="Write a 800-word SEO article. Markdown.", inject_memory=False)
            articles.append({"index": i+1, "chars": len(art)})
        except: pass
    return {"ok": True, "keyword": keyword, "generated": len(articles)}

PLUGIN_NAME = "content_network"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "SEO content site network: build sites, generate articles, deploy."
