# ====================================================================
# JARVIS OMEGA — Telegram Notifier (Jarvis talks to Sir directly)
# ====================================================================
"""
Sends Telegram messages to Sir and registers the bot webhook.

Why Telegram: it is the one free, phone-first channel where Jarvis can
reach Sir proactively — a push notification is a one-line alert, but a
Telegram message can carry the whole story (who wrote, what they said,
what Jarvis replied) and Sir can answer back in the same thread.

Setup (Sir's steps, once):
1. In Telegram, open @BotFather, send /newbot, pick a name + username.
   BotFather returns a bot token.
2. Start a chat with the new bot (tap Start) and send any message.
3. Open @userinfobot to get Sir's own Telegram user id (the chat id).
4. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in the Render env vars.
   The token never goes in chat, files, or the repo.

Both settings are read from env at call time (never cached), so a
redeploy picks them up. When either is unset, every function here is a
silent no-op — Telegram is an extra channel, never a hard dependency.
"""

from __future__ import annotations

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("telegram_notifier")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_DEFAULT_BASE_URL = "https://jarvis-ai-6c11.onrender.com"


def _configured() -> tuple[str, str] | None:
    """(token, chat_id) when Telegram is configured, else None."""
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


async def send_telegram_message(
    text: str, client: httpx.AsyncClient | None = None
) -> bool:
    """Send one Telegram message to Sir. Returns True when Telegram accepted it.

    Never raises. When Telegram is not configured, returns False.
    """
    configured = _configured()
    if not configured:
        log.debug("telegram_not_configured")
        return False
    token, chat_id = configured
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    assert client is not None
    try:
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="sendMessage"),
            json={"chat_id": chat_id, "text": text},
        )
        if resp.status_code != 200:
            log.warning("telegram_send_failed", status_code=resp.status_code)
            return False
        return bool(resp.json().get("ok"))
    except Exception as e:
        log.warning("telegram_send_error", error=str(e))
        return False
    finally:
        if own_client:
            await client.aclose()


async def set_telegram_webhook(
    base_url: str = "", client: httpx.AsyncClient | None = None
) -> bool:
    """Register the bot webhook so Sir can reply to Jarvis on Telegram.

    ``base_url`` is the public backend URL; empty = the live Render URL.
    Returns True when Telegram accepted the webhook. Never raises.
    """
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        log.debug("telegram_webhook_no_token")
        return False
    url = (base_url or settings.telegram_webhook_base_url or _DEFAULT_BASE_URL).rstrip("/")
    webhook_url = f"{url}/api/telegram/webhook"
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    assert client is not None
    try:
        resp = await client.post(
            _TELEGRAM_API.format(token=token, method="setWebhook"),
            json={"url": webhook_url},
        )
        if resp.status_code != 200:
            log.warning("telegram_webhook_failed", status_code=resp.status_code)
            return False
        ok = bool(resp.json().get("ok"))
        if ok:
            log.info("telegram_webhook_set", url=webhook_url)
        return ok
    except Exception as e:
        log.warning("telegram_webhook_error", error=str(e))
        return False
    finally:
        if own_client:
            await client.aclose()
