# Phase 19: Content Calendar Planner (REAL)
from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="content_calendar.generate", description="Generate a 30-day content calendar across all platforms.", parameters={"type":"object","properties":{"niche":{"type":"string"},"language":{"type":"string","default":"ar"},"platforms":{"type":"array","items":{"type":"string"},"default":["twitter","instagram","linkedin"]}},"required":["niche"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="content_calendar")
async def generate(niche: str, language: str = "ar", platforms: list = None) -> Dict[str, Any]:
    platforms = platforms or ["twitter","instagram","linkedin"]
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(user_message=f"Niche: {niche}, Language: {language}, Platforms: {platforms}", system_instructions='Generate a 30-day content calendar. Output STRICT JSON: {days:[{day:int, platform:string, content_type:string, topic:string, draft_hook:string}]}. Mix educational/entertaining/promotional content. Each day = one piece of content.', inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        calendar = json.loads(text)
        return {"ok": True, "niche": niche, "days_planned": len(calendar.get("days",[])), "calendar": calendar}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="content_calendar.auto_schedule", description="Push calendar items to marketing.schedule for auto-publishing.", parameters={"type":"object","properties":{"calendar":{"type":"object"}},"required":["calendar"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="content_calendar")
async def auto_schedule(calendar: dict) -> Dict[str, Any]:
    from plugins.marketing.plugin import marketing_schedule
    days = calendar.get("days", [])
    scheduled = 0
    base_date = datetime.utcnow()
    for d in days[:30]:
        try:
            when = (base_date + timedelta(days=d.get("day",1))).isoformat()
            await marketing_schedule(platform=d.get("platform","twitter"), content=d.get("draft_hook",""), scheduled_at=when)
            scheduled += 1
        except: pass
    return {"ok": True, "scheduled": scheduled, "total_days": len(days)}

PLUGIN_NAME = "content_calendar"; PLUGIN_VERSION = "1.0.0"
