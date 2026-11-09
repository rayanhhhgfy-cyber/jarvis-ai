# ====================================================================
# JARVIS OMEGA — DM Reply LLM (Groq primary, Gemini fallback)
# ====================================================================
"""
Generates replies for incoming Messenger / Instagram DMs.

Primary: Groq Cloud, Llama 3.3 70B Versatile — free tier, no card, and
the fastest inference available, which is what a live DM conversation
needs (a slow model means the other person waits in awkward silence).
Fallback: Google Gemini 2.5 Flash — also free tier, no card, and
stronger in Arabic than Llama, which matters for Jordanian callers.

Both keys live in env vars (GROQ_API_KEY, GEMINI_API_KEY). Neither is
logged. If Groq has no key or returns a rate-limit / server error, the
call falls through to Gemini automatically. If both fail, the caller
gets ``ok: False`` and the DM is left unanswered (never a fake reply).
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("dm_llm")

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

_SYSTEM_PROMPT = (
    "You are Rayyan Aljamal replying to a direct message from a friend. "
    "Reply in the same language the friend used (Jordanian Arabic when they "
    "write Arabic, English when they write English). Be warm, natural and "
    "brief — one or two short sentences, like a real person texting, never a "
    "formal letter. Do not mention that you are an AI or an assistant. Do "
    "not make promises about money, meetings or dates. If you do not know "
    "an answer, say you will check and get back to them."
)


def _messages(sender_name: str, incoming_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"DM from {sender_name}: {incoming_text}\n\nWrite the reply only.",
        },
    ]


async def _groq_reply(
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient,
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
                "messages": _messages(sender_name, incoming_text),
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
) -> str | None:
    api_key = settings.gemini_api_key
    if not api_key:
        log.debug("dm_gemini_no_key")
        return None
    prompt = (
        f"{_SYSTEM_PROMPT}\n\nDM from {sender_name}: {incoming_text}\n\n"
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
) -> dict[str, Any]:
    """
    Generate a reply for one incoming DM.

    Tries Groq first, then Gemini. Returns ``{"ok": True, "reply": ...,
    "model": "groq"|"gemini"}`` or ``{"ok": False, "error": ...}``.
    The caller's own client may be passed in (tests inject a mock
    transport); otherwise a fresh client is created per call.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    assert client is not None
    try:
        reply = await _groq_reply(sender_name, incoming_text, client)
        if reply:
            return {"ok": True, "reply": reply, "model": "groq"}
        reply = await _gemini_reply(sender_name, incoming_text, client)
        if reply:
            return {"ok": True, "reply": reply, "model": "gemini"}
        return {
            "ok": False,
            "error": "No LLM available: set GROQ_API_KEY or GEMINI_API_KEY.",
        }
    finally:
        if own_client:
            await client.aclose()
