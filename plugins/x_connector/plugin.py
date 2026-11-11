# ====================================================================
# JARVIS OMEGA — X Plugin (read + write DMs, OAuth 2.0 user context)
# ====================================================================
"""
X tools: read (status, DM conversations, DM events) and write
(send a DM, start a DM conversation). All of them need an OAuth 2.0
user token connected with /connect x (stored encrypted in the vault
under ``x_access_token`` / ``x_refresh_token``).

Read tools are TIER_0_OBSERVE. Write tools are TIER_4_EXTERNAL —
the approval gateway asks Sir before any of them runs, because each
one sends a message from his X account AND is billed by X
(pay-per-use, no free tier).
"""

from __future__ import annotations

from typing import Any

from backend.services import x_connector
from backend.tools import RiskTier, tool


@tool(
    name="x.status",
    description="Check the X connection: connected or not, and as whom.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="x",
)
async def x_status() -> dict[str, Any]:
    return await x_connector.status()


@tool(
    name="x.list_dm_conversations",
    description="List X DM conversations, newest first.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 10}},
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="x",
)
async def x_list_dm_conversations(limit: int = 10) -> dict[str, Any]:
    return await x_connector.list_dm_conversations(limit)


@tool(
    name="x.list_dm_events",
    description="List DM events in one X conversation, newest first.",
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["conversation_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="x",
)
async def x_list_dm_events(
    conversation_id: str, limit: int = 10
) -> dict[str, Any]:
    return await x_connector.list_dm_events(conversation_id, limit)


@tool(
    name="x.send_dm",
    description="Send a direct message into an existing X conversation.",
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["conversation_id", "text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="x_write",
)
async def x_send_dm(conversation_id: str, text: str) -> dict[str, Any]:
    return await x_connector.send_dm(conversation_id, text)


@tool(
    name="x.create_dm_conversation",
    description="Send a direct message to an X user, creating the conversation if needed.",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["user_id", "text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="x_write",
)
async def x_create_dm_conversation(user_id: str, text: str) -> dict[str, Any]:
    return await x_connector.create_dm_conversation(user_id, text)
