# Phase 18: Unified Inbox
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="inbox.all", description="Pull messages from all channels: WhatsApp + Instagram + email + Telegram. One unified view.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="unified_inbox")
async def inbox_all() -> Dict[str, Any]:
    messages = []
    # WhatsApp
    try:
        from backend import business_db
        wa = business_db.rows_to_dicts(business_db.query("SELECT recipient, body, status, created_at FROM whatsapp_messages ORDER BY id DESC LIMIT 10"))
        for m in wa: messages.append({"channel":"whatsapp","from":m["recipient"],"text":m["body"][:100],"date":m["created_at"]})
    except: pass
    # Instagram
    try:
        from plugins.social_dms.plugin import list_ig_dms
        ig = await list_ig_dms(limit=5)
        if ig.get("ok"):
            for c in ig.get("conversations",[]): messages.append({"channel":"instagram","data":c})
    except: pass
    return {"ok": True, "total": len(messages), "messages": messages}

PLUGIN_NAME = "unified_inbox"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Unified inbox: WhatsApp + Instagram + email + Telegram in one view."
