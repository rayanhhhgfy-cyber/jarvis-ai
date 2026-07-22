# Phase 19: Guest Post Outreach (REAL)
from __future__ import annotations
import re, json
from typing import Any, Dict, List
import httpx
from backend.tools import tool, RiskTier

@tool(name="guest_post.find_blogs", description="Find blogs in a niche that accept guest posts.", parameters={"type":"object","properties":{"niche":{"type":"string"},"limit":{"type":"integer","default":10}},"required":["niche"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="guest_post")
async def find_blogs(niche: str, limit: int = 10) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.google.com/search", params={"q": f"{niche} write for us OR guest post"}, headers={"User-Agent": "Mozilla/5.0"})
        urls = list(dict.fromkeys(re.findall(r'https?://[^\s"<>]+', r.text)))[:limit]
        urls = [u for u in urls if "google." not in u][:limit]
        return {"ok": True, "niche": niche, "blogs_found": len(urls), "blogs": urls}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="guest_post.write_pitch", description="Write a personalized guest post pitch email.", parameters={"type":"object","properties":{"blog_name":{"type":"string"},"niche":{"type":"string"},"topic_ideas":{"type":"array","items":{"type":"string"},"default":[]}},"required":["blog_name","niche"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="guest_post")
async def write_pitch(blog_name: str, niche: str, topic_ideas: list = None) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        pitch = await llm_service.get_response(user_message=f"Blog: {blog_name}, Niche: {niche}, Topics: {topic_ideas or []}", system_instructions="Write a short, professional guest post pitch email. Include 3 topic ideas. Friendly but not pushy. English.", inject_memory=False)
        return {"ok": True, "pitch": pitch.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="guest_post.write_article", description="Write a complete guest post article.", parameters={"type":"object","properties":{"title":{"type":"string"},"target_blog":{"type":"string"},"word_count":{"type":"integer","default":1500}},"required":["title"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="guest_post")
async def write_article(title: str, target_blog: str = "", word_count: int = 1500) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        article = await llm_service.get_response(user_message=f"Title: {title}, Target: {target_blog}, Words: {word_count}", system_instructions="Write a high-quality guest post article. Include: intro hook, 3-4 sections with actionable advice, conclusion, author bio placeholder. Markdown.", inject_memory=False)
        return {"ok": True, "article": article.strip(), "chars": len(article)}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "guest_post"; PLUGIN_VERSION = "1.0.0"
