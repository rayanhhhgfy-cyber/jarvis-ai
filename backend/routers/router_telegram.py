# ====================================================================
# JARVIS OMEGA — Telegram Router (Jarvis talks to Sir on Telegram)
# ====================================================================
"""
Telegram bot endpoints.

* ``POST /api/telegram/webhook`` — Telegram delivers incoming bot
  messages here. Only messages from Sir's own chat id are answered;
  anything else is ignored (the bot is Sir's private line, not a
  public bot). Sir's message goes to the same LLM brain as the
  dashboard chat, and the answer is sent back on Telegram.
* ``POST /api/telegram/setup`` — registers the webhook with Telegram
  (called once after the bot token is set; also auto-registered on
  backend startup).
* ``GET /api/telegram/status`` — whether the bot is configured. Never
  returns the token.
* ``POST /api/telegram/test`` — sends Sir a test message to confirm
  the bot reaches him.

The bot token and Sir's chat id live in env vars (TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID) — never in chat, files, or the repo.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.config import settings
from backend.services.telegram_notifier import (
    send_telegram_message,
    set_telegram_webhook,
)
from shared.logger import get_logger

log = get_logger("router_telegram")

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])

_TELEGRAM_SYSTEM = (
    "You are Jarvis, Rayyan's personal assistant. You are replying to "
    "Rayyan himself on Telegram. Answer helpfully and briefly, like a "
    "real person texting. You know everything about his projects and "
    "his DMs. If he asks about a message someone sent him, tell him "
    "what they said and what you replied. Never pretend to be Rayyan."
)


@router.get("/status")
async def telegram_status() -> dict[str, Any]:
    """Whether the Telegram bot is configured (never returns the token)."""
    return {
        "configured": bool(settings.telegram_bot_token.strip())
        and bool(settings.telegram_chat_id.strip()),
        "bot_token_set": bool(settings.telegram_bot_token.strip()),
        "chat_id_set": bool(settings.telegram_chat_id.strip()),
    }


@router.post("/setup")
async def telegram_setup(request: Request) -> dict[str, Any]:
    """Register the Telegram webhook (called once after the token is set)."""
    if not settings.telegram_bot_token.strip():
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set."}
    base_url = ""
    # Use the backend's own public host when no override is given.
    host = request.headers.get("host", "")
    if host:
        base_url = f"https://{host}"
    ok = await set_telegram_webhook(base_url=base_url)
    return {"ok": ok}


@router.post("/test")
async def telegram_test() -> dict[str, Any]:
    """Send Sir a test Telegram message to confirm the bot reaches him."""
    ok = await send_telegram_message(
        "Hello Sir, this is Jarvis on Telegram. Your bot is working — "
        "I can reach you here whenever I answer a DM or have something "
        "to tell you."
    )
    if not ok:
        return {
            "ok": False,
            "error": "Telegram is not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).",
        }
    return {"ok": True}


@router.post("/webhook")
async def telegram_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Receive a Telegram update and answer Sir when it is from him."""
    try:
        message = payload.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        if not text or not chat_id:
            return {"ok": True}
        expected = (settings.telegram_chat_id or "").strip()
        if not expected or chat_id != expected:
            # Not Sir — ignore silently (the bot is his private line).
            log.debug("telegram_webhook_ignored_stranger", chat_id=chat_id)
            return {"ok": True}
        from backend.services.llm_service import llm_service

        reply = await llm_service.get_response(
            user_message=text,
            system_instructions=_TELEGRAM_SYSTEM,
            inject_memory=True,
        )
        await send_telegram_message(reply or "Sorry Sir, I could not answer that.")
    except Exception as e:
        log.warning("telegram_webhook_failed", error=str(e))
    return {"ok": True}
