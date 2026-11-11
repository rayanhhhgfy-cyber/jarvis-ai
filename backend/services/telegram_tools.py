# ====================================================================
# JARVIS OMEGA — Telegram tools (2026-11-11)
# ====================================================================
"""
The bot's hands: the curated tools its brain may call from a Telegram
chat, so "send Omar a message" or "remind me at 5" actually happens
instead of being described.

These wrap the same operations the slash commands use (dm_responder,
the vault, the calendar, the contacts). They are ONLY reachable from
Sir's own verified Telegram chat id, and only when he asks in words —
so a write here is his direct instruction, the same as typing the
slash command himself, and it executes without the dashboard approval
gateway (which exists for the autonomous agent loop, not for Sir
telling Jarvis what to do).

Reads are TIER_0_OBSERVE; writes are TIER_4_EXTERNAL (honest labels).
The set is deliberately small: no shell, no code execution, no
deleting, no payments, no third-party posting — only Jarvis's own
jobs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.tools.registry import RiskTier, Tool
from shared.logger import get_logger

log = get_logger("telegram_tools")


def _str_param(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    func: Any,
    tier: RiskTier,
) -> Tool:
    return Tool(
        name=name,
        description=description,
        func=func,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
        },
        risk_tier=tier,
        category="telegram",
    )


async def _send_dm(name: str, text: str) -> str:
    """Send a DM to a person by name."""
    from backend.services.dm_responder import dm_responder

    result = await dm_responder.send_dm_to_name(name, text)
    if result.get("ok"):
        return (
            f"Sent to {result.get('sender_name')} on "
            f"{result.get('platform')}."
        )
    reason = result.get("reason", "unknown")
    if reason == "not_found":
        return (
            f"I could not find anyone named {name} in the recent DMs. "
            "Ask Sir for the exact name or the platform."
        )
    return f"Sending the DM failed ({reason})."


async def _list_recent_dms(limit: int = 5) -> str:
    """Recent DM activity (who messaged, what Jarvis replied)."""
    from backend.services.dm_responder import dm_responder

    entries = dm_responder.get_activity(limit=max(1, min(int(limit or 5), 20)))
    if not entries:
        return "No recent DMs."
    lines = []
    for e in entries:
        lines.append(
            f"- {e.get('sender_name')} ({e.get('platform')}): "
            f"\"{e.get('text', '')[:120]}\""
        )
    return "\n".join(lines)


async def _recent_messages_with(name: str, limit: int = 5) -> str:
    """The last messages exchanged with one person."""
    from backend.services.dm_responder import dm_responder

    needle = (name or "").strip().lower()
    entries = [
        e
        for e in dm_responder.get_activity(limit=20)
        if needle and needle in str(e.get("sender_name", "")).lower()
    ][: max(1, min(int(limit or 5), 10))]
    if not entries:
        return f"No recent conversation with {name}."
    lines = []
    for e in entries:
        lines.append(
            f"- {e.get('sender_name')}: \"{e.get('text', '')[:200]}\""
            f" (Jarvis replied: \"{e.get('reply', '')[:200]}\")"
        )
    return "\n".join(lines)


async def _set_reminder(text: str, when: str) -> str:
    """Set a reminder for Sir at a time he states in words."""
    from backend.services.dm_responder import dm_responder
    from backend.services.dm_time import parse_time

    parsed = parse_time(when or "")
    if not parsed:
        return (
            f"I could not understand the time {when!r}. "
            "Ask Sir for a time like 'tomorrow at 5pm' or 'in 30 minutes'."
        )
    result = dm_responder.add_reminder(text, parsed)
    if result.get("ok"):
        return (
            f"Reminder set for {parsed.strftime('%A %H:%M')}: {text}"
        )
    return "Could not set that reminder."


async def _list_calendar(when: str = "today") -> str:
    """What is on Sir's Jarvis calendar for a day he names."""
    from backend.services.dm_store import calendar as cal_store
    from backend.services.dm_time import parse_time

    parsed = parse_time(when or "today")
    day = (parsed or datetime.now(UTC)).astimezone(UTC).date().isoformat()
    entries = cal_store.all()
    found = [
        e for e in entries.values() if e.get("date") == day
    ]
    if not found:
        return f"Nothing on the calendar for {day}."
    lines = []
    for e in found:
        status = e.get("status", "busy")
        reason = (e.get("detail") or "").strip()
        lines.append(f"- {status}" + (f" ({reason})" if reason else ""))
    return f"On {day}:\n" + "\n".join(lines)


async def _lookup_contact(name: str) -> str:
    """A person's saved phone number or Instagram handle."""
    from backend.services.dm_store import contacts

    needle = (name or "").strip().lower()
    data = contacts.get(name, {}) or {}
    if not data:
        # Substring match across saved contacts.
        for key, value in contacts.all().items():
            if needle and needle in key.lower():
                data = value or {}
                name = key
                break
    if not data:
        return f"I have no saved contact for {name}."
    parts = []
    if data.get("phone"):
        parts.append(f"phone: {data['phone']}")
    if data.get("instagram"):
        parts.append(f"Instagram: {data['instagram']}")
    if data.get("notes"):
        parts.append(f"notes: {data['notes']}")
    return f"{name} — " + (", ".join(parts) if parts else "no details saved.")


async def _send_briefing() -> str:
    """Send Sir his morning briefing right now."""
    from backend.services.dm_responder import dm_responder

    ok = await dm_responder.send_morning_briefing()
    return "Briefing sent." if ok else "Could not send the briefing."


async def _get_status() -> str:
    """Whether the DM responder is on, and which accounts are connected."""
    from backend.services import dm_auth
    from backend.services.dm_responder import dm_responder

    status = dm_responder.get_status()
    connected = [
        s.get("name", "")
        for s in (dm_auth.connector_status(p) for p in dm_auth.PLATFORMS)
        if s.get("connected")
    ]
    responder = "on" if status.get("responder_enabled") else "off"
    return (
        f"DM responder is {responder}. "
        f"Connected: {', '.join(connected) if connected else 'nothing'}."
    )


async def _add_rule(rule: str) -> str:
    """Save a standing rule to Sir's permanent memory."""
    from backend.services.obsidian_vault import vault as obsidian_vault

    saved = obsidian_vault.add_rule(rule, source="telegram-tool")
    return f"Rule saved to permanent memory: {saved}" if saved else "Could not save that rule."


async def _remember_fact(fact: str) -> str:
    """Save a durable fact about Sir to his permanent memory."""
    from backend.services.obsidian_vault import vault as obsidian_vault

    saved = obsidian_vault.remember_fact(fact, source="telegram-tool")
    return f"Remembered: {saved}" if saved else "Could not save that fact."


async def _web_search(query: str) -> str:
    """Search the web for live information."""
    from backend.services.web_search_service import WebSearchService

    try:
        results = await WebSearchService().search(query, max_results=5)
    except (OSError, RuntimeError, ValueError) as e:
        return f"Web search failed: {e}"
    if not results:
        return f"No web results for {query!r}."
    lines = []
    for r in results:
        title = r.get("title", "")
        snippet = r.get("snippet", "") or r.get("body", "")
        lines.append(f"- {title}: {snippet[:200]}")
    return "\n".join(lines)


def telegram_tools() -> list[Tool]:
    """The curated tools the Telegram brain may call."""
    return [
        _tool(
            "telegram.send_dm",
            "Send a DM to a person by name (Instagram or Messenger). Use when Sir asks Jarvis to message someone.",
            {"name": _str_param("The person's name, as Sir said it."),
             "text": _str_param("The message to send.")},
            ["name", "text"],
            _send_dm,
            RiskTier.TIER_4_EXTERNAL,
        ),
        _tool(
            "telegram.list_recent_dms",
            "List the most recent DMs Jarvis answered (who messaged, what they said).",
            {"limit": {"type": "integer", "description": "How many to list (default 5)."}},
            [],
            _list_recent_dms,
            RiskTier.TIER_0_OBSERVE,
        ),
        _tool(
            "telegram.recent_messages_with",
            "The last messages exchanged with one person, so Sir can ask what they said.",
            {"name": _str_param("The person's name."),
             "limit": {"type": "integer", "description": "How many to show (default 5)."}},
            ["name"],
            _recent_messages_with,
            RiskTier.TIER_0_OBSERVE,
        ),
        _tool(
            "telegram.set_reminder",
            "Set a reminder for Sir at a time he states in words.",
            {"text": _str_param("What to remind him about."),
             "when": _str_param("When, in Sir's own words (e.g. 'tomorrow at 5pm', 'in 30 minutes').")},
            ["text", "when"],
            _set_reminder,
            RiskTier.TIER_1_REVERSIBLE,
        ),
        _tool(
            "telegram.list_calendar",
            "What is on Sir's Jarvis calendar for a day he names.",
            {"when": _str_param("The day, in Sir's own words (e.g. 'today', 'tomorrow', 'Friday').")},
            [],
            _list_calendar,
            RiskTier.TIER_0_OBSERVE,
        ),
        _tool(
            "telegram.lookup_contact",
            "Look up a person's saved phone number or Instagram handle from the contact memory.",
            {"name": _str_param("The person's name.")},
            ["name"],
            _lookup_contact,
            RiskTier.TIER_0_OBSERVE,
        ),
        _tool(
            "telegram.send_briefing",
            "Send Sir his morning briefing right now (weather, calendar, birthdays, overnight DMs).",
            {},
            [],
            _send_briefing,
            RiskTier.TIER_1_REVERSIBLE,
        ),
        _tool(
            "telegram.get_status",
            "Whether the DM responder is on, and which Instagram/Messenger accounts are connected.",
            {},
            [],
            _get_status,
            RiskTier.TIER_0_OBSERVE,
        ),
        _tool(
            "telegram.add_rule",
            "Save a standing rule to Sir's permanent memory.",
            {"rule": _str_param("The rule, in Sir's own words.")},
            ["rule"],
            _add_rule,
            RiskTier.TIER_1_REVERSIBLE,
        ),
        _tool(
            "telegram.remember_fact",
            "Save a durable fact about Sir to his permanent memory.",
            {"fact": _str_param("The fact, as a short plain sentence.")},
            ["fact"],
            _remember_fact,
            RiskTier.TIER_1_REVERSIBLE,
        ),
        _tool(
            "telegram.web_search",
            "Search the web for live information (news, scores, prices, facts).",
            {"query": _str_param("What to search for.")},
            ["query"],
            _web_search,
            RiskTier.TIER_0_OBSERVE,
        ),
    ]


def telegram_tool_schemas() -> list[dict[str, Any]]:
    """The tools as OpenAI function schemas, for the model."""
    return [t.to_openai_schema() for t in telegram_tools()]
