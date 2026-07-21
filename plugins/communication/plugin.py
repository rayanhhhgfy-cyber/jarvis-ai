# ====================================================================
# JARVIS OMEGA — Communication Plugin
# ====================================================================
"""
Phase 8 seed plugin: email / calendar / messaging integrations.

All credentials are read from the credentials vault
(`backend/services/credentials_vault.py`). If a credential is missing, the
tool returns a helpful "not configured" error rather than crashing.

Because every tool here has external side effects, they're all Tier 4
(External) — Sir must approve every call.
"""

from __future__ import annotations

import smtplib
import ssl
import urllib.parse
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Helper — pull credentials from the Phase 8 credentials vault
# --------------------------------------------------------------------

def _cred(key: str) -> Optional[str]:
    """Return a credential value, or None if the vault / key is missing."""
    try:
        from backend.services.credentials_vault import credentials_vault
        v = credentials_vault.get(key)
        return v if v else None
    except Exception:
        return None


def _missing(what: str) -> Dict[str, Any]:
    return {
        "configured": False,
        "error": (
            f"{what} is not configured. Open Settings → Credentials and add the "
            f"required {what} values."
        ),
    }


# --------------------------------------------------------------------
# Email (SMTP / IMAP)
# --------------------------------------------------------------------

@tool(
    name="email.send",
    description="Send an email via SMTP. Sender, recipient, subject, and body required.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "cc": {"type": "string", "description": "Optional comma-separated CC list."},
        },
        "required": ["to", "subject", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="communication",
)
async def email_send(to: str, subject: str, body: str, cc: str = "") -> Dict[str, Any]:
    host = _cred("smtp_host")
    port = _cred("smtp_port")
    user = _cred("smtp_user")
    password = _cred("smtp_password")
    sender = _cred("email_from") or user
    if not (host and port and user and password and sender):
        return _missing("SMTP / email_from")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, int(port), timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
        return {"sent": True, "to": to, "subject": subject}
    except Exception as e:
        return {"sent": False, "error": str(e)}


# --------------------------------------------------------------------
# Calendar (Google Calendar quick-add via API)
# --------------------------------------------------------------------

@tool(
    name="calendar.create",
    description="Create a calendar event. Uses Google Calendar API if GOOGLE_CALENDAR_TOKEN is configured.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "start": {"type": "string", "description": "ISO 8601 start datetime."},
            "end": {"type": "string", "description": "ISO 8601 end datetime."},
            "description": {"type": "string", "default": ""},
        },
        "required": ["summary", "start", "end"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="communication",
)
async def calendar_create(summary: str, start: str, end: str, description: str = "") -> Dict[str, Any]:
    token = _cred("google_calendar_token")
    calendar_id = _cred("google_calendar_id") or "primary"
    if not token:
        return _missing("google_calendar_token")
    import httpx
    payload = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(calendar_id)}/events"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code >= 400:
        return {"created": False, "status": resp.status_code, "error": resp.text[:300]}
    data = resp.json()
    return {"created": True, "event_id": data.get("id"), "html_link": data.get("htmlLink")}


# --------------------------------------------------------------------
# Messaging — Slack / Discord / Telegram (all webhook-or-bot based)
# --------------------------------------------------------------------

async def _post_webhook(url: str, json_payload: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=json_payload)
    if resp.status_code >= 400:
        return {"sent": False, "status": resp.status_code, "error": resp.text[:300]}
    return {"sent": True, "status": resp.status_code}


@tool(
    name="slack.send",
    description="Post a message to Slack. Requires slack_bot_token + a channel ID.",
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel name or ID (#general, C12345)."},
            "text": {"type": "string"},
        },
        "required": ["channel", "text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="communication",
)
async def slack_send(channel: str, text: str) -> Dict[str, Any]:
    token = _cred("slack_bot_token")
    if not token:
        return _missing("slack_bot_token")
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": channel, "text": text},
            headers={"Authorization": f"Bearer {token}"},
        )
    data = resp.json()
    if not data.get("ok"):
        return {"sent": False, "error": data.get("error", "unknown slack error")}
    return {"sent": True, "ts": data.get("ts")}


@tool(
    name="discord.send",
    description="Post a message to a Discord channel via a webhook URL.",
    parameters={
        "type": "object",
        "properties": {
            "webhook_name": {"type": "string", "description": "Key under which the webhook URL is stored in the credentials vault (e.g. 'discord_webhook_general')."},
            "text": {"type": "string"},
        },
        "required": ["webhook_name", "text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="communication",
)
async def discord_send(webhook_name: str, text: str) -> Dict[str, Any]:
    url = _cred(webhook_name)
    if not url:
        return _missing(webhook_name)
    return await _post_webhook(url, {"content": text})


@tool(
    name="telegram.send",
    description="Send a message via a Telegram bot. Requires telegram_bot_token + chat_id.",
    parameters={
        "type": "object",
        "properties": {
            "chat_id": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["chat_id", "text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="communication",
)
async def telegram_send(chat_id: str, text: str) -> Dict[str, Any]:
    token = _cred("telegram_bot_token")
    if not token:
        return _missing("telegram_bot_token")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return await _post_webhook(url, {"chat_id": chat_id, "text": text})


PLUGIN_NAME = "communication"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Email / calendar / Slack / Discord / Telegram integrations (Tier 4 — always ask)."
