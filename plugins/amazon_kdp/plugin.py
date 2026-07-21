# Phase 18: Amazon KDP Publisher (REAL)
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="kdp.generate_ebook", description="Generate a complete KDP-ready ebook: title + chapters + formatted HTML.", parameters={"type":"object","properties":{"topic":{"type":"string"},"language":{"type":"string","default":"ar"},"chapters":{"type":"integer","default":8}},"required":["topic"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="amazon_kdp")
async def generate_ebook(topic: str, language: str = "ar", chapters: int = 8) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        content = await llm_service.get_response(
            user_message=f"Topic: {topic}, Chapters: {chapters}",
            system_instructions=f"Write a complete ebook in {'Arabic' if language=='ar' else 'English'}. Title page + {chapters} chapters + conclusion. Each chapter 800+ words. Format as HTML with <h1>, <h2>, <p> tags. Ready for Amazon KDP upload.",
            inject_memory=False)
        out_dir = Path("./storage/kdp"); out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{topic[:50].replace(' ','_')}.html"
        path.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(path), "chars": len(content), "note": "Upload at kdp.amazon.com as an HTML file."}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="kdp.upload_guide", description="Step-by-step guide for uploading to Amazon KDP.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="amazon_kdp")
async def upload_guide() -> Dict[str, Any]:
    return {"ok": True, "url": "https://kdp.amazon.com", "steps": ["1. Sign up at kdp.amazon.com (free)", "2. Click 'Create' → 'Kindle eBook'", "3. Enter title + description + keywords", "4. Upload HTML file", "5. Set price ($2.99-9.99 recommended)", "6. Click 'Publish' — live in 24-72h", "7. Earn $2-10 royalty per sale forever"]}
