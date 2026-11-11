# ====================================================================
# JARVIS OMEGA — TikTok Plugin (Business Messaging, OAuth required)
# ====================================================================
"""
TikTok tools: read (status, conversations) and write (reply to a DM).

All of them need a TikTok Business account connected with
/connect tiktok (OAuth 2.0; tokens encrypted in the vault under
``tiktok_access_token`` / ``tiktok_refresh_token``).

Read tools are TIER_0_OBSERVE. The send tool is TIER_4_EXTERNAL —
the approval gateway asks Sir before it runs, because it sends a
message outside Jarvis. TikTok only allows replies inside the
48-hour window after the customer's last message; Jarvis can never
start a conversation.
"""

from __future__ import annotations

from typing import Any

from backend.services import tiktok_connector
from backend.tools import RiskTier, tool


@tool(
    name="tiktok.status",
    description="Check the TikTok Business Messaging connection state.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="tiktok",
)
async def tiktok_status() -> dict[str, Any]:
    return await tiktok_connector.status()


@tool(
    name="tiktok.list_conversations",
    description="List the TikTok Business Account's DM conversations.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 10}},
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="tiktok",
)
async def tiktok_list_conversations(limit: int = 10) -> dict[str, Any]:
    return await tiktok_connector.list_conversations(limit)


@tool(
    name="tiktok.send_message",
    description="Reply with a text message to a TikTok DM conversation. Only works inside the 48-hour reply window.",
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["conversation_id", "text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="tiktok",
)
async def tiktok_send_message(
    conversation_id: str, text: str
) -> dict[str, Any]:
    return await tiktok_connector.send_message(conversation_id, text)
