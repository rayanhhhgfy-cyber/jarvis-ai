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
naturally without re-introducing itself. Accuracy rules: never invent
facts, dates, prices, names, or scores — if it does not know, it says
so briefly and lets Rayyan check. Every reply is checked for
completeness before it is sent: a reply cut off mid-sentence is
trimmed back to its last complete sentence, and if there is no
complete sentence at all the other model is tried instead — a broken
message is never sent.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from backend.services.obsidian_vault import vault as obsidian_vault
from shared.logger import get_logger

log = get_logger("dm_llm")

GROQ_MODEL = "openai/gpt-oss-120b"
# Smaller Groq model: same free tier, a higher rate limit. When 120b
# trips its limit (or errors), the reply is retried on 20b before
# Gemini is even considered — Gemini's key is unset, so without this
# a 120b failure meant no reply at all.
GROQ_MODEL_20B = "openai/gpt-oss-20b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

_SYSTEM_PROMPT_FIRST = (
    "You are Jarvis, the personal assistant of Rayyan Aljamal, replying "
    "to a message from a friend of Rayyan's. This is the first "
    "time you are replying in this conversation, so introduce yourself "
    "briefly as Jarvis. Tell them Rayyan is busy right now and cannot "
    "respond at this time. If what they have is important, invite them "
    "to tell you and you will make sure Rayyan sees it. Reply in the "
    "same language they used (Jordanian Arabic when they write Arabic, "
    "English when they write English). Be warm, natural and brief — one "
    "or two short sentences, like a real person texting, never a formal "
    "letter. Do not pretend to be Rayyan. Do not make promises about "
    "money, meetings or dates. Never invent facts, dates, prices, names, "
    "or scores — if you do not know, say so briefly and tell them Rayyan "
    "will check when he is back. Always finish your sentences; never "
    "send a half-finished message."
)

_SYSTEM_PROMPT_FOLLOW_UP = (
    "You are Jarvis, the personal assistant of Rayyan Aljamal, "
    "continuing a conversation with a friend of Rayyan's. "
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
    "money, meetings or dates. Never invent facts, dates, prices, names, "
    "or scores — if you do not know, say so briefly and tell them Rayyan "
    "will check when he is back. Always finish your sentences; never "
    "send a half-finished message."
)

_GROUP_NOTE = (
    " This is a group chat, not a one-to-one DM. Address the person who "
    "wrote by name when you reply, and keep it brief so you do not "
    "dominate the group."
)

_WEB_TRIGGERS = (
    "weather", "طقس", "news", "أخبار", "search", "ابحث", "google",
    "what is", "who is", "who won", "what happened", "when is", "where is", "what are",
    "how much", "how many", "when did", "where did", "did it", "is it",
    "ما هو", "ما هي", "من هو", "من هي", "متى", "أين", "كم", "ما سعر",
    "latest", "current", "price", "سعر", "score", "نتيجة",
)


def _looks_like_web_question(text: str) -> bool:
    """True when the message is asking for live/external information."""
    lowered = (text or "").lower()
    return any(trigger in lowered for trigger in _WEB_TRIGGERS)


async def _maybe_web_context(incoming_text: str) -> str:
    """Search the web for a question that needs live info.

    Returns a short context block, or "" when the message is not a web
    question or the search fails. Never raises.
    """
    if not _looks_like_web_question(incoming_text):
        return ""
    try:
        from backend.services.web_search_service import web_search_service

        summary = await web_search_service.search_and_summarize(incoming_text)
        if not summary or "No web search results" in summary:
            return ""
        # Keep it short: the DM reply itself is capped at 300 tokens.
        return summary[:1500]
    except Exception as e:
        log.debug("dm_web_search_failed", error=str(e))
        return ""


# A reply is complete when it ends with terminal punctuation.
_TERMINAL_PUNCT = (".", "!", "?", "؟", "。", "…")


def _complete_reply(text: str) -> str | None:
    """Guarantee a reply is never sent half-finished.

    Returns the reply as-is when it ends with terminal punctuation.
    When the model was cut off mid-sentence (token cap), trims it back
    to the last complete sentence. Returns None when there is no
    complete sentence at all, so the caller can fall back to the other
    model instead of sending a broken message.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.endswith(_TERMINAL_PUNCT):
        return cleaned
    # Find the last sentence boundary and cut there.
    last_end = -1
    for punct in _TERMINAL_PUNCT:
        idx = cleaned.rfind(punct)
        last_end = max(last_end, idx)
    if last_end <= 0:
        return None
    return cleaned[: last_end + 1].strip()


def _messages(
    sender_name: str,
    incoming_text: str,
    first_reply: bool = True,
    is_group: bool = False,
    web_context: str = "",
) -> list[dict[str, str]]:
    prompt = _SYSTEM_PROMPT_FIRST if first_reply else _SYSTEM_PROMPT_FOLLOW_UP
    if is_group:
        prompt += _GROUP_NOTE
    # Sir's standing rules from his permanent memory (Obsidian vault):
    # a rule he stated is followed in every DM reply, not just noted.
    rules = obsidian_vault.rules_text()
    if rules:
        prompt += f"\n\nSir's standing rules (from his permanent memory — follow them):\n{rules}"
    user_text = f"DM from {sender_name}: {incoming_text}\n\nWrite the reply only."
    if web_context:
        user_text = (
            f"{web_context}\n\n"
            f"Use the web results above to answer when they are relevant. "
            f"DM from {sender_name}: {incoming_text}\n\nWrite the reply only."
        )
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_text},
    ]


async def _groq_reply(
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient,
    first_reply: bool = True,
    is_group: bool = False,
    web_context: str = "",
) -> str | None:
    """Groq reply: 120b first, 20b when 120b fails or rate-limits.

    Returns the completed reply text, or None when neither model
    could produce one (the caller then tries Gemini).
    """
    api_key = settings.groq_api_key
    if not api_key:
        log.debug("dm_groq_no_key")
        return None
    payload = {
        "messages": _messages(
            sender_name, incoming_text, first_reply, is_group, web_context
        ),
        "temperature": 0.7,
        "max_tokens": 300,
    }
    for model in (GROQ_MODEL, GROQ_MODEL_20B):
        try:
            resp = await client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, **payload},
                timeout=30.0,
            )
            if resp.status_code != 200:
                log.warning(
                    "dm_groq_error",
                    model=model,
                    status_code=resp.status_code,
                )
                continue
            choices = resp.json().get("choices") or []
            if not choices:
                continue
            text = (choices[0].get("message") or {}).get("content", "").strip()
            completed = _complete_reply(text)
            if completed:
                if model != GROQ_MODEL:
                    log.info("dm_groq_fell_back_to_20b")
                return completed
        except (httpx.HTTPError, ValueError) as e:
            log.warning("dm_groq_failed", model=model, error=str(e))
            continue
    return None


async def _gemini_reply(
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient,
    first_reply: bool = True,
    is_group: bool = False,
    web_context: str = "",
) -> str | None:
    api_key = settings.gemini_api_key
    if not api_key:
        log.debug("dm_gemini_no_key")
        return None
    base_prompt = _SYSTEM_PROMPT_FIRST if first_reply else _SYSTEM_PROMPT_FOLLOW_UP
    if is_group:
        base_prompt += _GROUP_NOTE
    prompt = (
        f"{base_prompt}"
        f"\n\nDM from {sender_name}: {incoming_text}\n\n"
        "Write the reply only."
    )
    if web_context:
        prompt = (
            f"{web_context}\n\n"
            f"Use the web results above to answer when they are relevant. "
            f"{prompt}"
        )
    try:
        resp = await client.post(
            GEMINI_URL,
            params={"key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 300, "temperature": 0.7},
            },
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
        return _complete_reply(text)
    except Exception as e:
        log.warning("dm_gemini_failed", error=str(e))
        return None


async def generate_dm_reply(
    platform: str,
    sender_name: str,
    incoming_text: str,
    client: httpx.AsyncClient | None = None,
    first_reply: bool = True,
    is_group: bool = False,
    media_url: str | None = None,
    media_type: str | None = None,
    contact_notes: str | None = None,
    tone: str | None = None,
    busy: str | None = None,
) -> dict[str, Any]:
    """
    Generate a reply for one incoming DM.

    Tries Groq first, then Gemini. Returns ``{"ok": True, "reply": ...,
    "model": "groq"|"gemini"}`` or ``{"ok": False, "error": ...}``.
    The caller's own client may be passed in (tests inject a mock
    transport); otherwise a fresh client is created per call.
    ``first_reply`` selects the intro prompt (Jarvis introduces itself,
    Rayyan is busy) versus the follow-up prompt (keep the conversation
    going without re-introducing). ``is_group`` marks a group chat so
    the reply addresses the sender by name and stays brief. When the
    message asks for live/external information, a web search runs first
    and its results are given to the LLM so it answers from real data,
    never invented facts. Every reply is passed through
    ``_complete_reply`` first, so a truncated message is trimmed to its
    last complete sentence — and if neither model can produce a complete
    sentence, the DM is left unanswered rather than sending a broken
    message. ``media_url``/``media_type`` carry a photo ("photo") or a
    voice note ("voice"): a voice note is transcribed first and the
    transcript becomes the incoming text; a photo is described and the
    description is given to the LLM so it replies about what is in it.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    assert client is not None
    try:
        # Voice note: hear it first — the transcript is the message.
        if media_type == "voice" and media_url:
            from backend.services.dm_media import transcribe_audio

            transcript = await transcribe_audio(media_url, client)
            if transcript:
                incoming_text = transcript
        # Photo: describe it so the reply is about what is in it.
        media_context = ""
        if media_type == "photo" and media_url:
            from backend.services.dm_media import describe_image

            description = await describe_image(media_url, client)
            if description:
                media_context = (
                    f"The person sent a photo. Description: {description}\n\n"
                    "Reply about the photo naturally, as if you saw it."
                )
        web_context = await _maybe_web_context(incoming_text)
        if media_context:
            web_context = f"{media_context}\n\n{web_context}" if web_context else media_context
        # Contact memory: what Sir recorded about this person.
        if contact_notes:
            notes_context = (
                f"What Rayyan told me about {sender_name}: {contact_notes}\n"
                "Use this to make the reply personal — mention what matters "
                "to them when it fits naturally. Do not reveal that you have "
                "notes about them."
            )
            web_context = f"{notes_context}\n\n{web_context}" if web_context else notes_context
        # Per-person tone: formal for teachers, casual for friends.
        if tone == "formal":
            tone_context = (
                "Reply formally and politely, as if speaking to a teacher. "
                "Use respectful language and proper greetings. "
                "Do not use slang or casual shortcuts."
            )
            web_context = f"{tone_context}\n\n{web_context}" if web_context else tone_context
        elif tone == "casual":
            tone_context = (
                "Reply casually, like a close friend texting. "
                "Relaxed, warm, and natural — no stiff or formal language."
            )
            web_context = f"{tone_context}\n\n{web_context}" if web_context else tone_context
        # Busy right now: Sir told Jarvis he is busy until a time for a
        # reason. Tell the sender plainly — do not wait to be asked.
        if busy:
            busy_context = (
                f"Rayyan is {busy}. Tell them this plainly in your reply — "
                "that he is busy and will get back to them once he can. "
                "Do not ask them to wait; just let them know."
            )
            web_context = f"{busy_context}\n\n{web_context}" if web_context else busy_context
        reply = await _groq_reply(
            sender_name, incoming_text, client, first_reply, is_group, web_context
        )
        if reply:
            return {"ok": True, "reply": reply, "model": "groq"}
        reply = await _gemini_reply(
            sender_name, incoming_text, client, first_reply, is_group, web_context
        )
        if reply:
            return {"ok": True, "reply": reply, "model": "gemini"}
        return {
            "ok": False,
            "error": "No LLM available: set GROQ_API_KEY or GEMINI_API_KEY.",
        }
    finally:
        if own_client:
            await client.aclose()
