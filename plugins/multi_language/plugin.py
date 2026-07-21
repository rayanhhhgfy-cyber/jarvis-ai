# Phase 18: Multi-language Generator (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="ml.translate_all", description="Translate content into Arabic + English + French + Turkish simultaneously.", parameters={"type":"object","properties":{"text":{"type":"string"},"source_language":{"type":"string","default":"ar"}},"required":["text"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="multi_language")
async def translate_all(text: str, source_language: str = "ar") -> Dict[str, Any]:
    from plugins.translate.plugin import translate_text
    results = {}
    targets = {"ar": "Arabic", "en": "English", "fr": "French", "tr": "Turkish"}
    for target_code, target_name in targets.items():
        if target_code == source_language:
            results[target_code] = text  # no translation needed
            continue
        try:
            r = await translate_text(text=text, target=target_code, source=source_language)
            results[target_code] = r.get("translated_text", "[translation failed]")
        except:
            results[target_code] = "[translation failed]"
    return {"ok": True, "source": source_language, "translations": results}
