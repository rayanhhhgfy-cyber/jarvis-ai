# Phase 18: Digital Product Factory
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="dpp.ebook_pipeline", description="Full ebook pipeline: topic -> 10k words -> cover -> ready to publish.", parameters={"type":"object","properties":{"topic":{"type":"string"},"language":{"type":"string","default":"ar"},"word_count":{"type":"integer","default":10000}},"required":["topic"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="digital_products")
async def ebook_pipeline(topic: str, language: str = "ar", word_count: int = 10000) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        content = await llm_service.get_response(user_message=f"Write a {word_count}-word ebook about: {topic}", system_instructions=f"Write a complete ebook in {'Arabic' if language=='ar' else 'English'}. Include title, chapters, conclusion. Markdown.", inject_memory=False)
        out = Path("./storage/digital_products/ebooks"); out.mkdir(parents=True, exist_ok=True)
        path = out / f"{topic[:50].replace(' ','_')}.md"; path.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(path), "chars": len(content)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="dpp.template_pack", description="Generate a pack of templates (Notion/Excel/PDF) for a niche.", parameters={"type":"object","properties":{"niche":{"type":"string"},"count":{"type":"integer","default":5}},"required":["niche"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="digital_products")
async def template_pack(niche: str, count: int = 5) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(user_message=f"Niche: {niche}, count: {count}", system_instructions="Generate template descriptions. Output JSON: {templates: [{name, description, format}]}", inject_memory=False)
        return {"ok": True, "templates": json.loads(reply.strip().lstrip("`").rstrip("`").replace("json","",1) if reply.strip().startswith("```") else reply)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="dpp.publish_gumroad", description="Guide: publish a product on Gumroad (free, instant).", parameters={"type":"object","properties":{"product_name":{"type":"string"},"price_usd":{"type":"number","default":9}},"required":["product_name"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="digital_products")
async def publish_gumroad(product_name: str, price_usd: float = 9) -> Dict[str, Any]:
    import webbrowser; webbrowser.open("https://gumroad.com/signup")
    return {"ok": True, "url": "https://gumroad.com/signup", "product": product_name, "price": price_usd, "instructions": "Sign up -> New Product -> Upload file -> Set price -> Publish"}

PLUGIN_NAME = "digital_products"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Digital product factory: ebooks, templates, Gumroad publishing."
