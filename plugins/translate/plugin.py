# ====================================================================
# JARVIS OMEGA - Free Translate Plugin (LibreTranslate)
# ====================================================================
"""
Phase 10 plugin: free translation via LibreTranslate public instances.

  * ``translate.text``      - translate text between languages.
  * ``translate.detect``    - detect the language of a text.
  * ``translate.languages`` - list supported languages.

The official public endpoint is https://libretranslate.com (rate-limited,
free for low volume). Self-hosted instances are also supported by overriding
the ``translate_base_url`` credential in the vault.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


def _base_url() -> str:
    try:
        from backend.services.credentials_vault import credentials_vault
        custom = credentials_vault.get("translate_base_url")
        if custom:
            return custom.rstrip("/")
    except Exception:
        pass
    return "https://libretranslate.com"


def _api_key() -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get("translate_api_key") or None
    except Exception:
        return None


@tool(
    name="translate.text",
    description="Translate text from source language to target language (ISO codes like 'en', 'es', 'fr', 'zh').",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to translate. Max ~5000 chars per call."},
            "source": {"type": "string", "default": "auto", "description": "Source ISO code, or 'auto'."},
            "target": {"type": "string", "description": "Target ISO code, e.g. 'en'."},
        },
        "required": ["text", "target"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="translate",
)
async def translate_text(text: str, target: str, source: str = "auto") -> Dict[str, Any]:
    if len(text) > 5000:
        return {"ok": False, "error": "text too long (>5000 chars); chunk it"}
    payload: Dict[str, Any] = {
        "q": text,
        "source": source,
        "target": target,
        "format": "text",
    }
    key = _api_key()
    if key:
        payload["api_key"] = key
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{_base_url()}/translate", data=payload)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        return {
            "ok": True,
            "translated_text": data.get("translatedText"),
            "source": source,
            "target": target,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="translate.detect",
    description="Detect the language of a text.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="translate",
)
async def translate_detect(text: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"q": text}
    key = _api_key()
    if key:
        payload["api_key"] = key
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{_base_url()}/detect", data=payload)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        # Returns list of {language, confidence} sorted by confidence.
        if isinstance(data, list) and data:
            top = data[0]
            return {
                "ok": True,
                "language": top.get("language") if isinstance(top, dict) else str(top),
                "confidence": top.get("confidence") if isinstance(top, dict) else None,
                "alternatives": data[:5],
            }
        return {"ok": True, "language": None, "raw": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="translate.languages",
    description="List supported languages and their ISO codes.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="translate",
)
async def translate_languages() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_base_url()}/languages")
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        out = [
            {"code": lang.get("code"), "name": lang.get("name")}
            for lang in data
        ]
        return {"ok": True, "count": len(out), "languages": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "translate"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free translation via LibreTranslate (text, detect, languages)."
