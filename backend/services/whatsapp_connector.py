# ====================================================================
# JARVIS OMEGA — WhatsApp Connector (Cloud API, read status + write)
# ====================================================================
"""
WhatsApp connector: send messages via the WhatsApp Cloud API (Meta).

The permanent access token lives encrypted in the credentials vault
under ``whatsapp_token`` and the phone number id under
``whatsapp_phone_number_id``. Tokens from the ``WHATSAPP_TOKEN`` and
``WHATSAPP_PHONE_NUMBER_ID`` env vars are used as fallbacks when the
vault is empty.

Sir connects with /connect whatsapp on Telegram: he pastes the
permanent token and the phone number id, Jarvis verifies the token
with GET /me BEFORE storing it, and neither value is ever logged or
echoed back. /disconnect whatsapp removes them — the only way they
leave the vault.

IMPORTANT — the number registered on the Cloud API must be a
DEDICATED number. It cannot be a personal WhatsApp number, and once
a number is registered on the Cloud API it cannot be used in the
phone WhatsApp app again. Free-form text only works inside a
24-hour reply window (after the contact last messaged); outside that
window only approved message templates may be sent — that is what
``send_template`` is for.

Send operations are exposed as tools at TIER_4_EXTERNAL, so the
approval gateway asks Sir before any of them runs.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("whatsapp_connector")

_FB = "https://graph.facebook.com/v18.0"
VAULT_KEY = "whatsapp_token"
VAULT_PHONE_NUMBER_ID_KEY = "whatsapp_phone_number_id"


def token() -> str | None:
    """The WhatsApp permanent access token: vault first, env fallback."""
    try:
        saved = credentials_vault.get(VAULT_KEY)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("whatsapp_token_vault_read_failed", error=str(e))
        saved = None
    if saved:
        return saved
    env = (os.environ.get("WHATSAPP_TOKEN") or "").strip()
    return env or None


def phone_number_id() -> str | None:
    """The WhatsApp phone number id: vault first, env fallback."""
    try:
        saved = credentials_vault.get(VAULT_PHONE_NUMBER_ID_KEY)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("whatsapp_phone_number_id_vault_read_failed", error=str(e))
        saved = None
    if saved:
        return saved
    env = (os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    return env or None


def is_connected() -> bool:
    """True only when both the token and the phone number id are set."""
    return token() is not None and phone_number_id() is not None


def _headers(tok: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }


async def verify_token(
    tok: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Check a token with GET /me. Returns account + phone number id, or None.

    The phone number id is a separate credential, so it is read from
    the vault (or env) rather than from the /me response.
    """
    tok = (tok or "").strip()
    if not tok:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(f"{_FB}/me", headers=_headers(tok))
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "account_id": data.get("id"),
            "phone_number_id": phone_number_id(),
        }
    except (httpx.HTTPError, ValueError) as e:
        log.warning("whatsapp_verify_failed", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


def save_token(tok: str) -> None:
    """Store a verified token encrypted in the vault."""
    credentials_vault.set(VAULT_KEY, (tok or "").strip(), category="connector")


def save_phone_number_id(phone_id: str) -> None:
    """Store the phone number id encrypted in the vault."""
    credentials_vault.set(
        VAULT_PHONE_NUMBER_ID_KEY, (phone_id or "").strip(), category="connector"
    )


def delete_token() -> bool:
    """Remove the token from the vault. Returns True when one was stored."""
    return credentials_vault.delete(VAULT_KEY)


def delete_phone_number_id() -> bool:
    """Remove the phone number id from the vault. True when one was stored."""
    return credentials_vault.delete(VAULT_PHONE_NUMBER_ID_KEY)


async def status(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Connection state: connected, phone number id."""
    if not is_connected():
        return {"connected": False, "phone_number_id": phone_number_id()}
    tok = token()
    info = await verify_token(tok or "", client=client)
    if info is None:
        return {"connected": False, "phone_number_id": phone_number_id()}
    return {"connected": True, "phone_number_id": info.get("phone_number_id")}


async def _request(
    method: str,
    path: str,
    tok: str | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One Cloud API call. Returns {"ok", "status", "data"/"error"}."""
    tok = tok or token()
    if not tok:
        return {"ok": False, "status": 0, "error": "WhatsApp is not connected."}
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.request(
            method, f"{_FB}{path}", headers=_headers(tok),
            json=json_body, params=params,
        )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        if resp.status_code == 204:
            return {"ok": True, "status": 204, "data": {}}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "status": 0, "error": str(e)[:300]}
    finally:
        if own_client:
            await client.aclose()


def _require_phone_number_id() -> str | None:
    return phone_number_id()


# --------------------------------------------------------------------
# Write — every one of these needs the token and the phone number id;
# the tools gate them at TIER_4_EXTERNAL so Sir approves before any
# of them runs.
# --------------------------------------------------------------------

async def send_message(
    to: str, body: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Send a free-form text message. Only works inside the 24-hour
    reply window; outside it, use send_template instead."""
    tok = token()
    phone_id = _require_phone_number_id()
    if not tok or not phone_id:
        return {
            "ok": False,
            "error": "WhatsApp is not connected — /connect whatsapp first.",
        }
    result = await _request(
        "POST", f"/{phone_id}/messages", tok=tok,
        json_body={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    messages = (result["data"] or {}).get("messages") or []
    if not messages:
        return {"ok": False, "error": "WhatsApp accepted the message but returned no id."}
    return {"ok": True, "message_id": messages[0].get("id")}


async def send_template(
    to: str,
    template_name: str,
    language: str = "en_US",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send an approved message template. This is the only kind of
    message allowed outside the 24-hour reply window."""
    tok = token()
    phone_id = _require_phone_number_id()
    if not tok or not phone_id:
        return {
            "ok": False,
            "error": "WhatsApp is not connected — /connect whatsapp first.",
        }
    result = await _request(
        "POST", f"/{phone_id}/messages", tok=tok,
        json_body={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {"name": template_name, "language": {"code": language}},
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    messages = (result["data"] or {}).get("messages") or []
    if not messages:
        return {"ok": False, "error": "WhatsApp accepted the template but returned no id."}
    return {"ok": True, "message_id": messages[0].get("id")}


async def mark_read(
    message_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Mark an incoming message as read (blue ticks)."""
    tok = token()
    phone_id = _require_phone_number_id()
    if not tok or not phone_id:
        return {
            "ok": False,
            "error": "WhatsApp is not connected — /connect whatsapp first.",
        }
    result = await _request(
        "POST", f"/{phone_id}/messages", tok=tok,
        json_body={
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "read": True}
