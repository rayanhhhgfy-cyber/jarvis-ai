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

import re
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

# "tell <name> <message>" — Sir asks Jarvis to send a DM for him.
_SEND_RE = re.compile(
    r"^(?:tell|message|send to|send a message to)\s+(\S+(?:\s+\S+)?)\s+(.+)$",
    re.IGNORECASE,
)
# "summarize ... with <name>" — Sir asks for a conversation summary.
_SUMMARIZE_RE = re.compile(
    r"summar\w*\s+(?:.*?\s+)?with\s+(\S+(?:\s+\S+)?)\s*$",
    re.IGNORECASE,
)


async def _summarize_conversation(name: str) -> str:
    """Summarize the recent DM exchanges with one person, via the LLM.

    Uses the activity feed (the last 20 replies), so it covers recent
    conversations. Returns a short summary, or a clear "nothing found".
    """
    from backend.services.dm_responder import dm_responder
    from backend.services.llm_service import llm_service

    needle = (name or "").strip().lower()
    entries = [
        e for e in dm_responder.get_activity(limit=20)
        if needle in (e.get("sender_name") or "").lower()
    ]
    if not entries:
        return f"I have no recent DM activity with {name} to summarize."
    lines = []
    for entry in reversed(entries):
        lines.append(
            f"{entry.get('sender_name', '')}: {entry.get('text', '')[:200]} "
            f"-> Jarvis: {entry.get('reply', '')[:200]}"
        )
    summary = await llm_service.get_response(
        user_message=(
            "Summarize this DM conversation briefly: what was said, "
            "what was decided, and what is still open.\n\n" + "\n".join(lines)
        ),
        system_instructions=(
            "You are Jarvis. Summarize the conversation in a few short "
            "lines for Rayyan, in the language he used."
        ),
        inject_memory=False,
    )
    return summary or f"I could not summarize the conversation with {name}."


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
    """Receive a Telegram update and answer Sir when it is from him.

    Before the normal chat, three special intents are handled:
    * A pending tricky-message draft: "send" sends the draft as-is,
      any other text is sent as Sir's own reply instead.
    * "tell <name> <message>": Jarvis sends that DM for Sir.
    * "summarize ... with <name>": Jarvis summarizes the recent
      conversation with that person from the DM activity feed.
    Otherwise the message goes to the chat LLM, with the recent DM
    activity included as context so Sir can ask about his DMs.
    """
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
        from backend.services.dm_responder import dm_responder

        # --- Pending draft (feature 8): Sir approves or replaces it. ---
        draft = dm_responder.get_pending_draft()
        if draft:
            if text.lower() in ("send", "send it", "yes", "ok", "okay", "ارسل", "أرسل"):
                result = await dm_responder.send_draft_reply(
                    draft["thread_id"], draft["draft_reply"]
                )
                if result.get("ok"):
                    await send_telegram_message(
                        f"Sent to {result.get('sender_name', '')}."
                    )
                else:
                    await send_telegram_message(
                        "I could not send that draft — the account may need reconnecting."
                    )
            else:
                result = await dm_responder.send_draft_reply(draft["thread_id"], text)
                if result.get("ok"):
                    await send_telegram_message(
                        f"Sent your reply to {result.get('sender_name', '')}."
                    )
                else:
                    await send_telegram_message(
                        "I could not send that reply — the account may need reconnecting."
                    )
            return {"ok": True}

        # --- "tell <name> <message>" (feature 6): send a DM for Sir. ---
        send_match = _SEND_RE.match(text)
        if send_match:
            name, message_text = send_match.group(1), send_match.group(2)
            result = await dm_responder.send_dm_to_name(name, message_text)
            if result.get("reason") == "not_found" and " " in name:
                # The name regex is greedy (up to two words) and may have
                # swallowed the first word of the message ("tell Omar I
                # will..." -> name "Omar I"). Retry with one-word name.
                first, rest = name.split(" ", 1)
                message_text = f"{rest} {message_text}"
                result = await dm_responder.send_dm_to_name(first, message_text)
                name = first
            if result.get("ok"):
                await send_telegram_message(
                    f"Sent to {result.get('sender_name', name)}."
                )
            else:
                await send_telegram_message(
                    f"I could not find a conversation with {name}."
                )
            return {"ok": True}

        # --- "summarize ... with <name>" (feature 9): summarize the thread. ---
        summary_match = _SUMMARIZE_RE.search(text)
        if summary_match:
            name = summary_match.group(1)
            summary = await _summarize_conversation(name)
            await send_telegram_message(summary)
            return {"ok": True}

        # --- Normal chat, with recent DM activity as context (feature 5). ---
        from backend.services.llm_service import llm_service

        activity = dm_responder.get_activity(limit=10)
        context = ""
        if activity:
            lines = []
            for entry in reversed(activity):
                lines.append(
                    f"- {entry.get('sender_name', '')} "
                    f"({entry.get('platform', '')}): "
                    f"{entry.get('text', '')[:120]} "
                    f"-> Jarvis: {entry.get('reply', '')[:120]}"
                )
            context = (
                "[Recent DM activity — use this when Sir asks about his DMs]\n"
                + "\n".join(lines)
                + "\n\n"
            )
        reply = await llm_service.get_response(
            user_message=f"{context}Rayyan (Telegram): {text}",
            system_instructions=_TELEGRAM_SYSTEM,
            inject_memory=True,
        )
        await send_telegram_message(reply or "Sorry Sir, I could not answer that.")
    except Exception as e:
        log.warning("telegram_webhook_failed", error=str(e))
    return {"ok": True}
