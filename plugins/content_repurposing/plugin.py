# JARVIS OMEGA - Content Repurposing Machine (Phase 16)
from __future__ import annotations
import json
from typing import Any, Dict, List
from backend.tools import tool, RiskTier

@tool(name="repurpose.from_text", description="Take ONE piece of content and generate 6 formats: blog post, 10 tweets, LinkedIn carousel, IG carousel, newsletter, podcast script. Arabic or English.", parameters={"type":"object","properties":{"source_content":{"type":"string"},"language":{"type":"string","default":"ar","enum":["ar","en"]},"tone":{"type":"string","default":"engaging"}},"required":["source_content"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="content_repurposing")
async def from_text(source_content: str, language: str = "ar", tone: str = "engaging") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    lang = "Arabic" if language == "ar" else "English"
    outputs = {}
    formats = [
        ("blog_post", f"Write a 800-word blog post in {lang}. Tone: {tone}. Markdown."),
        ("tweets", f"Write 10 tweets in {lang} from this content. Each under 280 chars. Output JSON array of strings."),
        ("linkedin_post", f"Write a LinkedIn thought-leadership post in {lang}. Professional + insightful. 3-4 paragraphs."),
        ("instagram_caption", f"Write an Instagram caption in {lang} with 10-15 hashtags. Under 2200 chars."),
        ("newsletter_issue", f"Write a newsletter issue in {lang} expanding this content. 500 words. Subject + body."),
        ("podcast_script", f"Write a 3-minute podcast narration script in {lang}. Conversational."),
    ]
    for fmt, instruction in formats:
        try:
            reply = await llm_service.get_response(user_message=f"Source content:\n{source_content[:3000]}", system_instructions=instruction, inject_memory=False)
            outputs[fmt] = reply.strip()
        except Exception as e:
            outputs[fmt] = f"[Error: {e}]"
    return {"ok": True, "formats_generated": len(outputs), "outputs": outputs}

@tool(name="repurpose.from_video", description="Take a YouTube/video transcript and repurpose into 6 formats.", parameters={"type":"object","properties":{"transcript":{"type":"string"},"language":{"type":"string","default":"ar"}},"required":["transcript"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="content_repurposing")
async def from_video(transcript: str, language: str = "ar") -> Dict[str, Any]:
    return await from_text(source_content=transcript, language=language, tone="conversational")

PLUGIN_NAME = "content_repurposing"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "1 input to 6 outputs: blog, tweets, LinkedIn, IG, newsletter, podcast."
