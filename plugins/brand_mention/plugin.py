# Phase 18: Brand Mention Monitor (REAL)
from __future__ import annotations
import re
from datetime import datetime
from typing import Any, Dict
import httpx
from backend.tools import tool, RiskTier

@tool(name="mentions.scan", description="Scan Google for brand mentions. Returns latest results.", parameters={"type":"object","properties":{"brand_name":{"type":"string","default":"JARVIS OMEGA"}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="brand_mention")
async def scan_mentions(brand_name: str = "JARVIS OMEGA") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get("https://www.google.com/search", params={"q": f'"{brand_name}"', "num": 20}, headers={"User-Agent": "Mozilla/5.0"})
        urls = list(dict.fromkeys(re.findall(r'https?://[^\s"<>]+', resp.text)))[:15]
        urls = [u for u in urls if "google." not in u and "youtube.com/results" not in u]
        return {"ok": True, "brand": brand_name, "mentions_found": len(urls), "urls": urls, "scanned_at": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
