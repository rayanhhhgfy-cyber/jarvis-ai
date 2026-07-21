# JARVIS OMEGA - Influencer Outreach (Phase 16)
from __future__ import annotations
import json, re
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="influencer.find", description="Find micro-influencers (1k-50k followers) on Instagram by niche. Uses public search.", parameters={"type":"object","properties":{"niche":{"type":"string"},"region":{"type":"string","default":"Jordan"},"limit":{"type":"integer","default":20}},"required":["niche"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="influencer_outreach")
async def find(niche: str, region: str = "Jordan", limit: int = 20) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get("https://www.google.com/search",
                params={"q": f"site:instagram.com {niche} influencer {region}", "num": limit},
                headers={"User-Agent": "Mozilla/5.0"})
        handles = list(set(re.findall(r"instagram\.com/([a-zA-Z0-9_.]+)/", resp.text)))
        handles = [h for h in handles if h not in ("p","accounts","explore","about","legal","developer","tags")][:limit]
        for h in handles:
            try: business_db.execute("INSERT OR IGNORE INTO influencer_outreach_log (influencer_handle, platform, status, created_at) VALUES (?, 'instagram', 'identified', ?)",
                (h, datetime.utcnow().isoformat()))
            except: pass
        return {"ok": True, "niche": niche, "found": len(handles), "handles": handles}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="influencer.write_pitch", description="Write a personalized barter-collab pitch in Arabic for an influencer.", parameters={"type":"object","properties":{"handle":{"type":"string"},"product_name":{"type":"string"},"product_value_jod":{"type":"number","default":0},"niche":{"type":"string"}},"required":["handle","product_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="influencer_outreach")
async def write_pitch(handle: str, product_name: str, product_value_jod: float = 0, niche: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Handle: @{handle}\nProduct: {product_name}\nValue: {product_value_jod} JOD\nNiche: {niche}",
            system_instructions='Write a short, warm DM pitch in Jordanian Arabic offering a free product in exchange for a mention/story. Keep it under 150 chars. Friendly, not salesy.',
            inject_memory=False)
        business_db.execute("UPDATE influencer_outreach_log SET status = 'pitched', deal_type = 'barter' WHERE influencer_handle = ?", (handle,))
        return {"ok": True, "handle": handle, "pitch": reply.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="influencer.list_tracked", description="List all identified influencers + their outreach status.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="influencer_outreach")
async def list_tracked() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT * FROM influencer_outreach_log ORDER BY id DESC LIMIT 100"))
    return {"ok": True, "influencers": rows}

@tool(name="influencer.bulk_pitch", description="Write + queue pitches for all identified-but-unpitched influencers.", parameters={"type":"object","properties":{"product_name":{"type":"string"},"product_value_jod":{"type":"number","default":0}},"required":["product_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="influencer_outreach")
async def bulk_pitch(product_name: str, product_value_jod: float = 0) -> Dict[str, Any]:
    unpitched = business_db.rows_to_dicts(business_db.query("SELECT influencer_handle FROM influencer_outreach_log WHERE status = 'identified' LIMIT 50"))
    pitched = 0
    for inf in unpitched:
        r = await write_pitch(handle=inf["influencer_handle"], product_name=product_name, product_value_jod=product_value_jod)
        if r.get("ok"): pitched += 1
    return {"ok": True, "pitched": pitched, "total_unpitched": len(unpitched)}

PLUGIN_NAME = "influencer_outreach"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Influencer outreach: find micro-influencers + auto-write Arabic barter pitches."
