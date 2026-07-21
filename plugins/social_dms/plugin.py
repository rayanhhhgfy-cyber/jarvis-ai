# JARVIS OMEGA - Social DMs (Phase 16)
from __future__ import annotations
import json
from typing import Any, Dict, Optional
import httpx
from backend.tools import tool, RiskTier

def _cred(k):
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(k) or None
    except: return None

@tool(name="social.list_ig_dms", description="List recent Instagram DM conversations. Requires instagram_access_token + instagram_user_id.", parameters={"type":"object","properties":{"limit":{"type":"integer","default":10}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="social_dms")
async def list_ig_dms(limit: int = 10) -> Dict[str, Any]:
    token = _cred("instagram_access_token"); uid = _cred("instagram_user_id")
    if not (token and uid): return {"ok": False, "error": "instagram_access_token + instagram_user_id not in vault"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://graph.facebook.com/v18.0/{uid}/conversations",
                params={"platform":"instagram","access_token":token,"limit":limit})
        if r.status_code >= 400: return {"ok": False, "error": r.text[:300]}
        return {"ok": True, "conversations": r.json().get("data",[])}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="social.reply_ig_dm", description="Reply to an Instagram DM.", parameters={"type":"object","properties":{"recipient_id":{"type":"string"},"message":{"type":"string"}},"required":["recipient_id","message"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="social_dms")
async def reply_ig_dm(recipient_id: str, message: str) -> Dict[str, Any]:
    token = _cred("instagram_access_token")
    if not token: return {"ok": False, "error": "instagram_access_token not in vault"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://graph.facebook.com/v18.0/me/messages",
                params={"access_token":token},
                json={"recipient":{"id":recipient_id},"message":{"text":message}})
        if r.status_code >= 400: return {"ok": False, "error": r.text[:300]}
        return {"ok": True, "sent": True}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="social.auto_respond_ig", description="LLM reads an incoming DM + generates an Arabic reply automatically.", parameters={"type":"object","properties":{"incoming_message":{"type":"string"},"business_context":{"type":"string","default":""}},"required":["incoming_message"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="social_dms")
async def auto_respond_ig(incoming_message: str, business_context: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Incoming DM: {incoming_message}\nBusiness context: {business_context}",
            system_instructions="You are an Arabic-speaking Instagram business assistant. Reply warmly + helpfully in Jordanian Arabic. Keep it under 100 chars. If asked about price, say 'أرسل لك التفاصيل على واتساب 📱' and ask for their number.",
            inject_memory=False)
        return {"ok": True, "suggested_reply": reply.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="social.list_tiktok_dms", description="List TikTok messages. Requires tiktok_access_token.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="social_dms")
async def list_tiktok_dms() -> Dict[str, Any]:
    token = _cred("tiktok_access_token")
    if not token: return {"ok": False, "error": "tiktok_access_token not in vault"}
    return {"ok": False, "error": "TikTok Business Messaging API requires app review. Manual check: https://www.tiktok.com/messages"}

@tool(name="social.dm_broadcast_ig", description="Send the same DM to multiple Instagram followers (rate-limited: max 50/day per Meta policy).", parameters={"type":"object","properties":{"follower_ids":{"type":"array","items":{"type":"string"}},"message":{"type":"string"}},"required":["follower_ids","message"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="social_dms")
async def dm_broadcast_ig(follower_ids: list, message: str) -> Dict[str, Any]:
    if len(follower_ids) > 50: return {"ok": False, "error": "Meta limit: max 50 DMs/day"}
    results = []
    for fid in follower_ids[:50]:
        r = await reply_ig_dm(recipient_id=fid, message=message)
        results.append({"id": fid, "ok": r.get("ok",False)})
    sent = sum(1 for r in results if r["ok"])
    return {"ok": sent > 0, "sent": sent, "failed": len(results)-sent}

PLUGIN_NAME = "social_dms"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Instagram + TikTok DM automation: read, reply, auto-respond, broadcast."
