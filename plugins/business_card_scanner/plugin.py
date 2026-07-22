# Phase 19: Business Card Scanner (REAL)
from __future__ import annotations
import base64
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="bcard.scan", description="Scan a business card photo and extract name, phone, email, company. Then add to CRM.", parameters={"type":"object","properties":{"image_path":{"type":"string"}},"required":["image_path"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business_card_scanner")
async def scan(image_path: str) -> Dict[str, Any]:
    if not Path(image_path).exists(): return {"ok": False, "error": "image not found"}
    from backend.services.llm_service import llm_service
    try:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        # Use Qwen VL for OCR
        import httpx
        from backend.config import settings
        if not settings.openrouter_api_key: return {"ok": False, "error": "OPENROUTER_API_KEY not configured"}
        data_url = f"data:image/jpeg;base64,{b64}"
        payload = {"model": settings.qwen_vision_model, "messages": [{"role":"user","content":[{"type":"text","text":"Extract all contact info from this business card. Output STRICT JSON: {name, title, company, phone, email, website, address}"},{"type":"image_url","image_url":{"url":data_url}}]}], "temperature":0.1, "max_tokens":500}
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type":"application/json"}
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers)
        if r.status_code >= 400: return {"ok": False, "error": f"API error: {r.status_code}"}
        text = r.json()["choices"][0]["message"]["content"]
        import json
        clean = text.strip().lstrip("`").rstrip("`")
        if clean.startswith("json"): clean = clean[4:]
        contact = json.loads(clean)
        return {"ok": True, **contact}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="bcard.add_to_crm", description="Add a scanned business card contact to the CRM.", parameters={"type":"object","properties":{"name":{"type":"string"},"phone":{"type":"string","default":""},"email":{"type":"string","default":""}},"required":["name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="business_card_scanner")
async def add_to_crm(name: str, phone: str = "", email: str = "") -> Dict[str, Any]:
    from plugins.unified_crm.plugin import crm_capture
    return await crm_capture(name=name, phone=phone, email=email, source="business_card")

PLUGIN_NAME = "business_card_scanner"; PLUGIN_VERSION = "1.0.0"
