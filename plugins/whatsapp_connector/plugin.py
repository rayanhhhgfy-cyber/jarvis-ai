# ====================================================================
# JARVIS OMEGA — WhatsApp Connector Plugin (Cloud API)
# ====================================================================
"""
WhatsApp tools, backed by the WhatsApp Cloud API (Meta). They need a
permanent access token and a phone number id connected with
/connect whatsapp (stored encrypted in the vault under
``whatsapp_token`` and ``whatsapp_phone_number_id``).

Read (status) is TIER_0_OBSERVE. Sends are TIER_4_EXTERNAL — the
approval gateway asks Sir before any of them runs, because each one
sends a message outside Jarvis.

The number registered on the Cloud API must be a DEDICATED number —
it cannot be a personal WhatsApp number, and once registered it
cannot be used in the phone WhatsApp app again. Free-form text only
works inside the 24-hour reply window; outside it, only approved
templates may be sent (whatsapp.send_template).
"""

from __future__ import annotations

from typing import Any

from backend.services import whatsapp_connector
from backend.tools import RiskTier, tool


@tool(
    name="whatsapp.send_message",
    description="Send a free-form WhatsApp text message. Only works inside the 24-hour reply window; outside it, use whatsapp.send_template.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="whatsapp_connector",
)
async def whatsapp_send_message(to: str, body: str) -> dict[str, Any]:
    return await whatsapp_connector.send_message(to, body)


@tool(
    name="whatsapp.send_template",
    description="Send an approved WhatsApp message template. The only kind of message allowed outside the 24-hour reply window.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "template_name": {"type": "string"},
            "language": {"type": "string", "default": "en_US"},
        },
        "required": ["to", "template_name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="whatsapp_connector",
)
async def whatsapp_send_template(
    to: str, template_name: str, language: str = "en_US"
) -> dict[str, Any]:
    return await whatsapp_connector.send_template(to, template_name, language)


@tool(
    name="whatsapp.status",
    description="Check the WhatsApp Cloud API connection state.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="whatsapp_connector",
)
async def whatsapp_status() -> dict[str, Any]:
    return await whatsapp_connector.status()
