# ====================================================================
# JARVIS OMEGA — DM Reply LLM (Groq primary, Gemini fallback)
# ====================================================================
"""
Generates replies for incoming Messenger / Instagram DMs.

Primary: Groq Cloud, openai/gpt-oss-120b — free tier, no card, and the
fastest inference available, which is what a live DM conversation needs
(a slow model means the other person waits in awkward silence).
Fallback: Google Gemini 2.5 Flash — also free tier, no card, and
stronger in Arabic than most models, which matters for Jordanian
callers.

Both keys live in env vars (GROQ_API_KEY, GEMINI_API_KEY). Neither is
logged. If Groq has no key or returns a rate-limit / server error, the
call falls through to Gemini automatically. If both fail, the caller
gets ``ok: False`` and the DM is left unanswered (never a fake reply).

Reply behaviour (Sir's standing rule): Jarvis answers as itself, not
as Rayyan. On the first reply in a conversation it introduces itself,
says Rayyan is busy and cannot respond right now, and invites the
person to tell Jarvis if it is important — Jarvis will make sure
Rayyan sees it. On follow-ups it keeps the conversation going
naturally without re-introducing itself.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("dm_llm")

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

_SYSTEM_PROMPT_FIRST = (
    "You are Jarvis, the personal assistant of Rayyan Aljamal, replying "
    "to a direct message from a friend of Rayyan's. This is the first "
    "time you are replying in this conversation, so introduce yourself "
    "briefly as Jarvis. Tell them Rayyan is busy right now and cannot "
    "respond at this time. If what they have is important, invite them "
    "to tell you and you will make sure Rayyan sees it. Reply in the "
    "same language they used (Jordanian Arabic when they write Arabic, "
    "English when they write English). Be warm, natural and brief — one "
    "or two short sentences, like a real person texting, never a formal "
    "letter. Do not pretend to be Rayyan. Do not make promises about "
    "money, meetings or dates."
)

_SYSTEM_PROMPT_FOLLOW_UP = (
    "You are Jarvis, the personal assistant of Rayyan Aljamal, "
    "continuing a direct-message conversation with a friend of Rayyan's. "
    "You have already introduced yourself as Jarvis in this "
    "conversation, so do not introduce yourself again. Keep the "
    "conversation going naturally: answer their questions as best you "
    "can, take their message, and reassure them Rayyan will see it. "
    "Rayyan is busy and cannot respond right now; if what they have is "
    "important, invite them to tell you and you will make sure Rayyan "
    "sees it. Reply in the same language they used (Jordanian Arabic "
    "when they write Arabic, English when they write English). Be warm, "
    "natural and brief — one or two short sentences, like a real person "
    "texting. Do not pretend to be Rayyan. Do not make promises about "
    "money, meetings or dates."
)


def _messages(
    sender_name: str, incoming_text: str, first_reply: bool = True
) -> list[dict[str, str]]:
    prompt = _SYSTEM_PROMPT_FIRST if first_reply else _SYSTEM_PROMPT_FOLLOW_UP
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"DM from {sender_name}: {incoming_text}\n\nWrite the reply only.",
        },
    ]


async def _groq_reply(
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient,
    first_reply: bool = True,
) -> str | None:
    api_key = settings.groq_api_key
    if not api_key:
        log.debug("dm_groq_no_key")
        return None
    try:
        resp = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": _messages(sender_name, incoming_text, first_reply),
                "temperature": 0.7,
                "max_tokens": 150,
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            log.warning("dm_groq_error", status_code=resp.status_code)
            return None
        choices = resp.json().get("choices") or []
        if not choices:
            return None
        text = (choices[0].get("message") or {}).get("content", "").strip()
        return text or None
    except Exception as e:
        log.warning("dm_groq_failed", error=str(e))
        return None


async def _gemini_reply(
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient,
    first_reply: bool = True,
) -> str | None:
    api_key = settings.gemini_api_key
    if not api_key:
        log.debug("dm_gemini_no_key")
        return None
    prompt = (
        f"{_SYSTEM_PROMPT_FIRST if first_reply else _SYSTEM_PROMPT_FOLLOW_UP}"
        f"\n\nDM from {sender_name}: {incoming_text}\n\n"
        "Write the reply only."
    )
    try:
        resp = await client.post(
            GEMINI_URL,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30.0,
        )
        if resp.status_code != 200:
            log.warning("dm_gemini_error", status_code=resp.status_code)
            return None
        candidates = resp.json().get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except Exception as e:
        log.warning("dm_gemini_failed", error=str(e))
        return None


async def generate_dm_reply(
    platform: str,
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient | None = None,
    first_reply: bool = True,
) -> dict[str, Any]:
    """
    Generate a reply for one incoming DM.

    Tries Groq first, then Gemini. Returns ``{"ok": True, "reply": ...,
    "model": "groq"|"gemini"}`` or ``{"ok": False, "error": ...}``.
    The caller's own client may be passed in (tests inject a mock
    transport); otherwise a fresh client is created per call.
    ``first_reply`` selects the intro prompt (Jarvis introduces itself,
    Rayyan is busy) versus the follow-up prompt (keep the conversation
    going without re-introducing).
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    assert client is not None
    try:
        reply = await _groq_reply(sender_name, incoming_text, client, first_reply)
        if reply:
            return {"ok": True, "reply": reply, "model": "groq"}
        reply = await _gemini_reply(sender_name, incoming_text, client, first_reply)
        if reply:
            return {"ok": True, "reply": reply, "model": "gemini"}
        return {
            "ok": False,
            "error": "No LLM available: set GROQ_API_KEY or GEMINI_API_KEY.",
        }
    finally:
        if own_client:
            await client.aclose()
