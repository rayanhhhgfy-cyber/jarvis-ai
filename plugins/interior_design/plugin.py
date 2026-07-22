# Phase 19: AI Interior Designer (REAL)
from __future__ import annotations
import base64, io
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="interior.analyze_room", description="Analyze a room photo and suggest improvements.", parameters={"type":"object","properties":{"image_path":{"type":"string"}},"required":["image_path"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="interior_design")
async def analyze_room(image_path: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        from plugins.agent_vision import _call_qwen_vl
        result = await _call_qwen_vl(b64_image=b64, mime_type="image/jpeg", instruction="You are an interior designer. Analyze this room. What works? What does not? Suggest 5 specific improvements. Output STRICT JSON: {strengths:[string], weaknesses:[string], suggestions:[string]}", raw_text=False)
        return {"ok": True, **result}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="interior.generate_redesign", description="Generate a redesigned version of a room using Pollinations AI.", parameters={"type":"object","properties":{"image_path":{"type":"string"},"style":{"type":"string","default":"modern minimalist","enum":["modern minimalist","scandinavian","industrial","bohemian","luxury arabic"]}},"required":["image_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="interior_design")
async def generate_redesign(image_path: str, style: str = "modern minimalist") -> Dict[str, Any]:
    from plugins.media_free.plugin import media_image_pollinations
    import urllib.parse
    prompt = f"Redesign this room in {style} style, professional interior photography, magazine quality"
    result = await media_image_pollinations(prompt=prompt, width=1024, height=768)
    return result

PLUGIN_NAME = "interior_design"; PLUGIN_VERSION = "1.0.0"
