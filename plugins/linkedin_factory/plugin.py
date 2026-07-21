# JARVIS OMEGA - LinkedIn Content Factory (Phase 16)
from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="linkedin.post_write", description="Generate a LinkedIn thought-leadership post in Arabic.", parameters={"type":"object","properties":{"topic":{"type":"string"},"style":{"type":"string","default":"insight","enum":["insight","story","data","controversy","howto"]}},"required":["topic"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="linkedin_factory")
async def post_write(topic: str, style: str = "insight") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    style_map = {"insight":"Share a counterintuitive insight about","story":"Tell a personal story about","data":"Share data-backed findings about","controversy":"Take a bold stance on","howto":"Give a practical how-to guide for"}
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}",
            system_instructions=f"{style_map.get(style, style_map['insight'])} {topic}. Write a LinkedIn post in Arabic. Hook in first line. 150-300 words. End with a question. No hashtags in body.",
            inject_memory=False)
        post = reply.strip()
        lid = business_db.execute("INSERT INTO linkedin_posts_log (content, topic, status, created_at) VALUES (?, ?, 'draft', ?)",
            (post, topic, datetime.utcnow().isoformat()))
        return {"ok": True, "post": post, "post_id": lid}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="linkedin.schedule_week", description="Generate 5 LinkedIn posts for the week (Mon-Fri). Different style each day.", parameters={"type":"object","properties":{"niche":{"type":"string"}},"required":["niche"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="linkedin_factory")
async def schedule_week(niche: str) -> Dict[str, Any]:
    styles = ["insight", "story", "data", "controversy", "howto"]
    days = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
    posts = []
    for day, style in zip(days, styles):
        p = await post_write(topic=f"{niche} ({day} theme: {style})", style=style)
        if p.get("ok"): posts.append({"day": day, "style": style, "post": p["post"][:200]+"..."})
    return {"ok": True, "niche": niche, "posts_generated": len(posts), "posts": posts}

@tool(name="linkedin.list_posts", description="List all generated LinkedIn posts.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="linkedin_factory")
async def list_posts() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT id, topic, status, created_at FROM linkedin_posts_log ORDER BY id DESC LIMIT 50"))
    return {"ok": True, "posts": rows}

PLUGIN_NAME = "linkedin_factory"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "LinkedIn content factory: daily Arabic authority posts."
