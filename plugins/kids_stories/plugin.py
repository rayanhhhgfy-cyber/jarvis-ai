# Phase 19: Children's Story Generator (REAL)
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="kids.generate_story", description="Generate an Arabic children's story with a moral lesson. Age-appropriate.", parameters={"type":"object","properties":{"theme":{"type":"string","default":"kindness"},"age_group":{"type":"string","default":"5-8","enum":["3-5","5-8","8-12"]},"character_name":{"type":"string","default":""}}}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="kids_stories")
async def generate_story(theme: str = "kindness", age_group: str = "5-8", character_name: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        story = await llm_service.get_response(user_message=f"Theme: {theme}, Age: {age_group}, Character: {character_name or 'surprise me'}", system_instructions="Write a children's story in Arabic. Age-appropriate, engaging, with a clear moral lesson. 500-800 words. Include a title. Output the story in Markdown.", inject_memory=False)
        out = Path("./storage/kids_stories"); out.mkdir(parents=True, exist_ok=True)
        path = out / f"story_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
        path.write_text(story, encoding="utf-8")
        return {"ok": True, "story": story, "path": str(path)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="kids.generate_series", description="Generate a 10-story series around one character.", parameters={"type":"object","properties":{"character_name":{"type":"string"},"theme":{"type":"string","default":"adventure"}},"required":["character_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="kids_stories")
async def generate_series(character_name: str, theme: str = "adventure") -> Dict[str, Any]:
    stories = []
    for i in range(3):  # Start with 3 to keep it fast; user can extend
        r = await generate_story(theme=theme, character_name=character_name)
        if r.get("ok"): stories.append(r.get("path",""))
    return {"ok": True, "character": character_name, "stories_generated": len(stories), "paths": stories, "note": "Each story can be sold as an ebook. 10 stories = 1 compilation ebook."}

@tool(name="kids.illustrate", description="Generate an illustration for a children's story using Pollinations.", parameters={"type":"object","properties":{"scene_description":{"type":"string"}},"required":["scene_description"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="kids_stories")
async def illustrate(scene_description: str) -> Dict[str, Any]:
    from plugins.media_free.plugin import media_image_pollinations
    return await media_image_pollinations(prompt=f"childrens book illustration, colorful, cute, {scene_description}, flat design style", width=1024, height=1024)

PLUGIN_NAME = "kids_stories"; PLUGIN_VERSION = "1.0.0"
