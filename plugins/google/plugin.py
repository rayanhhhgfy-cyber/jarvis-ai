# ====================================================================
# JARVIS OMEGA — Google Plugin (Gmail + Calendar + Drive)
# ====================================================================
"""
Google tools: Gmail, Calendar and Drive behind one OAuth login.

Read tools are TIER_0_OBSERVE. Write tools (send mail, create an
event) are TIER_4_EXTERNAL — the approval gateway asks Sir before
any of them runs.
"""

from __future__ import annotations

from typing import Any

from backend.services import google_connector
from backend.tools import RiskTier, tool


@tool(
    name="google.list_messages",
    description="List Gmail messages, optionally filtered by a search query.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 10},
        },
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="google",
)
async def google_list_messages(
    query: str = "", limit: int = 10
) -> dict[str, Any]:
    return await google_connector.list_messages(query, limit)


@tool(
    name="google.get_message",
    description="Read one Gmail message by id (from, subject, snippet).",
    parameters={
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="google",
)
async def google_get_message(message_id: str) -> dict[str, Any]:
    return await google_connector.get_message(message_id)


@tool(
    name="google.send_message",
    description="Send an email from Sir's Gmail.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="google",
)
async def google_send_message(
    to: str, subject: str, body: str
) -> dict[str, Any]:
    return await google_connector.send_message(to, subject, body)


@tool(
    name="google.list_events",
    description="List events on Sir's Google Calendar (his real calendar).",
    parameters={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "default": ""},
            "time_max": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 10},
        },
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="google",
)
async def google_list_events(
    time_min: str = "", time_max: str = "", limit: int = 10
) -> dict[str, Any]:
    return await google_connector.list_events(time_min, time_max, limit)


@tool(
    name="google.create_event",
    description="Create an event on Sir's Google Calendar.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "description": {"type": "string", "default": ""},
        },
        "required": ["summary", "start", "end"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="google",
)
async def google_create_event(
    summary: str, start: str, end: str, description: str = ""
) -> dict[str, Any]:
    return await google_connector.create_event(summary, start, end, description)


@tool(
    name="google.list_files",
    description="List files in Sir's Google Drive.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 10},
        },
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="google",
)
async def google_list_files(
    query: str = "", limit: int = 10
) -> dict[str, Any]:
    return await google_connector.list_files(query, limit)


@tool(
    name="google.search_files",
    description="Search Sir's Google Drive by file name.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="google",
)
async def google_search_files(
    query: str, limit: int = 10
) -> dict[str, Any]:
    return await google_connector.search_files(query, limit)
