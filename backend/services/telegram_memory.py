# ====================================================================
# JARVIS OMEGA — Telegram auto-memory (2026-11-11)
# ====================================================================
"""
The bot learns from talking, not just from commands.

After a free-chat turn with Sir, this module asks the small Groq
model (20b — cheap, fast) to pull out anything DURABLE from the
exchange — a preference, a project detail, a person, a commitment, a
decision — and saves it to the Obsidian vault's Facts note, where it
is injected into the brain on every later reply. Nothing is invented:
the extractor may only repeat what Sir actually said, and it returns
NOTHING when there is nothing durable to keep.

This is best-effort and never blocks the reply: the webhook fires it
as a background task after answering. If it fails or finds nothing,
nothing is saved and the conversation continues.
"""

from __future__ import annotations

import httpx

from backend.config import settings
from backend.services.obsidian_vault import vault as obsidian_vault
from shared.logger import get_logger

log = get_logger("telegram_memory")

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL_20B = "openai/gpt-oss-20b"

# Short messages that can never hold a durable fact — skip the
# extraction call entirely for these.
_TRIVIAL = {
    "hi", "hello", "hey", "ok", "okay", "thanks", "thank you", "bye",
    "yes", "no", "nope", "sure", "fine", "good", "great", "nice",
    "مرحبا", "هلا", "اهلا", "تمام", "شكرا", "طيب", "نعم", "لا",
}

_EXTRACT_SYSTEM = (
    "You extract durable facts about Rayyan from a short conversation. "
    "A durable fact is something that will still be true tomorrow and "
    "that Jarvis should remember: a preference, a project detail, a "
    "person and how Rayyan relates to them, a commitment, a decision, "
    "a date or deadline Rayyan stated, a thing Rayyan likes or dislikes. "
    "Rules: only repeat what Rayyan actually said — never invent, infer "
    "or guess. Never include the briefing, the weather, or anything "
    "Jarvis itself said. Never include secrets, passwords or tokens. "
    "If there is nothing durable, reply with exactly the word NOTHING. "
    "Otherwise reply with one fact per line, each a short plain sentence, "
    "no bullets, no numbering, no extra words."
)


def _worth_extracting(user_text: str) -> bool:
    """Cheap gate: skip trivial messages before spending an LLM call."""
    text = (user_text or "").strip().lower()
    if len(text) < 10:
        return False
    return text.strip(" .!؟") not in _TRIVIAL


async def extract_facts(user_text: str, reply_text: str) -> list[str]:
    """Durable facts from one exchange, or [] when there are none."""
    if not _worth_extracting(user_text):
        return []
    api_key = settings.groq_api_key
    if not api_key:
        return []
    exchange = (
        f"Rayyan: {user_text.strip()}\nJarvis: {(reply_text or '').strip()}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            response = await client.post(
                _GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _GROQ_MODEL_20B,
                    "messages": [
                        {"role": "system", "content": _EXTRACT_SYSTEM},
                        {"role": "user", "content": exchange},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
            )
    except (httpx.HTTPError, ValueError) as e:
        log.debug("telegram_memory_extract_failed", error=str(e))
        return []
    if response.status_code != 200:
        log.debug(
            "telegram_memory_extract_failed", status=response.status_code
        )
        return []
    try:
        content = (
            response.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except (ValueError, KeyError, IndexError, AttributeError):
        return []
    if not content or content.strip().upper() == "NOTHING":
        return []
    facts = [
        line.strip().lstrip("-•0123456789. ").strip()
        for line in content.splitlines()
        if line.strip()
        and line.strip().upper() != "NOTHING"
    ]
    return [f for f in facts if len(f) >= 10]


async def auto_save_facts(user_text: str, reply_text: str) -> int:
    """Extract durable facts from a turn and save them to the vault.

    Returns how many new facts were saved (0 when there were none).
    Never raises — memory must never break the conversation.
    """
    try:
        facts = await extract_facts(user_text, reply_text)
        saved = 0
        for fact in facts:
            if obsidian_vault.remember_fact(fact, source="telegram-auto"):
                saved += 1
        if saved:
            log.info("telegram_memory_saved", count=saved)
        return saved
    except (OSError, RuntimeError, ValueError) as e:
        log.debug("telegram_memory_save_failed", error=str(e))
        return 0
