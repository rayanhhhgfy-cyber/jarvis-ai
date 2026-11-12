# ====================================================================
# JARVIS OMEGA — briefing-request words tests (2026-11-12)
# ====================================================================
"""
Rayyan's screen recording (2026-11-12 ~10:07): he asked for his morning
briefing by voice note and got 4 voice notes of web-search results with
sources instead. Cause: a briefing request only reached the stored
briefing when it matched the narrow English resend patterns or the
literal "briefing"/"النشرة" trigger — any other phrasing (Arabic words
for briefing, "today's summary", ...) fell through to the LLM fallback,
which answered with the telegram.web_search tool.

The fix: one shared matcher (_is_briefing_request) in the resend
handler and in the "briefing ..." trigger, so no briefing request in
any words can reach the LLM. A plain news question is still a web
search, not a briefing. A settings change ("make my briefing at 9am")
must still reach _handle_briefing, not the resend handler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import router_telegram
from backend.routers.router_telegram import (
    _is_briefing_request,
    _is_briefing_settings_change,
)
from backend.services import dm_store

FAKE_BRIEFING = (
    "☀️ Good morning, Rayyan! — Thursday, November 12\n"
    "🌤️ Weather in Irbid: Clear skies, 22°C\n"
    "📅 Nothing on your calendar today."
)

# Every new English phrase the matcher must catch.
ENGLISH_REQUESTS = (
    "briefing",
    "morning briefing",
    "my briefing",
    "today's briefing",
    "today briefing",
    "the briefing",
    "summary",
    "today's summary",
    "my summary",
    "send me the briefing",
    "send me my briefing",
    "give me today's summary",
)

# Every new Arabic word the matcher must catch.
ARABIC_REQUESTS = (
    "البريفينغ",
    "بريفينغ",
    "الموجز",
    "موجز",
    "الملخص",
    "ملخص",
    "النشرة",
    "نشرة",
    "ابعت البريفينغ",
    "أرسل لي الملخص",
    "اعطيني الموجز",
    "جيب لي النشرة",
    "ابعت لي ملخص اليوم",
)


def _telegram_app():
    test_app = FastAPI()
    test_app.include_router(router_telegram.router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


def _webhook_voice_post(transcript, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111},
                    "voice": {"file_id": "voice123", "duration": 5}},
    })


def _prep(monkeypatch, tmp_path, briefing_text=FAKE_BRIEFING):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    monkeypatch.setattr(dm_store.briefing, "_path", tmp_path / "briefing.json")
    monkeypatch.setattr(dm_store.briefing, "_loaded", False)
    monkeypatch.setattr(dm_store.briefing, "_data", {})
    monkeypatch.setattr(dm_store.telegram_history, "_path", tmp_path / "telegram_history.json")
    monkeypatch.setattr(dm_store.telegram_history, "_loaded", False)
    monkeypatch.setattr(dm_store.telegram_history, "_data", {})
    if briefing_text is not None:
        # Stored "now", so the 24-hour resend window always holds no
        # matter when the suite runs.
        dm_store.briefing.set(
            "last_sent",
            {
                "text": briefing_text,
                "sent_at": datetime.now(UTC).isoformat(),
                "language": "en",
            },
        )


def _responder():
    fake = MagicMock()
    fake.get_pending_draft.return_value = None
    fake.get_activity.return_value = []
    return fake


# --- The matcher itself ------------------------------------------------


@pytest.mark.parametrize("text", ENGLISH_REQUESTS)
def test_is_briefing_request_english(text):
    assert _is_briefing_request(text)


@pytest.mark.parametrize("text", ARABIC_REQUESTS)
def test_is_briefing_request_arabic(text):
    assert _is_briefing_request(text)


def test_is_briefing_request_keeps_old_resend_patterns():
    assert _is_briefing_request("resend it")
    assert _is_briefing_request("send it to me the full thing no deletion")
    assert _is_briefing_request("No I want today the one you gave me today")
    assert _is_briefing_request("Nope I want it now")


def test_is_briefing_request_send_verb_alone_is_not_a_briefing():
    # A send verb with no briefing word is a DM, not a briefing request.
    assert not _is_briefing_request("ابعتها لعمر")
    assert not _is_briefing_request("أرسل له رسالة")


@pytest.mark.parametrize("text", (
    "what's the news in Jordan today",
    "what is the news",
    "tell me the news",
    "الأخبار",
    "hello",
    "what do you know about yourself",
    "",
    "send Omar a voice note",
    "resend it on Instagram",
    "summarize my DMs with Omar",
))
def test_is_briefing_request_rejects_news_and_other(text):
    assert not _is_briefing_request(text)


# --- The settings guard -------------------------------------------------


@pytest.mark.parametrize("text", (
    "make my briefing at 9am",
    "briefing at 8am",
    "briefing arabic",
    "briefing in english",
    "briefing voice",
    "briefing news off",
    "briefing without the weather",
    "briefing calendar off",
))
def test_is_briefing_settings_change(text):
    assert _is_briefing_settings_change(text)


@pytest.mark.parametrize("text", (
    "send my briefing as a voice note",
    "briefing now",
    "send me the briefing",
    "ابعت البريفينغ",
    "today's summary",
    "briefing",
    "الموجز",
    # A resend phrasing that happens to mention a language is still a
    # resend, not a settings change.
    "resend it as a voice note in English",
    "send it to me the full thing no deletion in a voice note",
))
def test_is_not_a_settings_change(text):
    assert not _is_briefing_settings_change(text)


# --- Routing: every new word/phrase reaches the stored briefing --------


@pytest.mark.parametrize("text", ENGLISH_REQUESTS + ARABIC_REQUESTS)
@pytest.mark.asyncio
async def test_briefing_request_routes_to_stored_briefing(
    monkeypatch, tmp_path, text,
):
    """The stored briefing goes out as text; the LLM never runs."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.telegram_tools._web_search",
              new=AsyncMock(return_value="search results")) as mock_search,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response_with_tools = AsyncMock(return_value="hallucinated")
        assert _webhook_post(text, update_id=1).status_code == 200
    mock_llm.get_response_with_tools.assert_not_called()
    mock_search.assert_not_called()
    mock_voice.assert_not_called()
    mock_text.assert_called_once()
    assert mock_text.call_args.args[0] == FAKE_BRIEFING


@pytest.mark.asyncio
async def test_voice_note_briefing_request_sends_briefing_as_voice(
    monkeypatch, tmp_path,
):
    """His exact bug, replayed: a voice note asking for the briefing
    (Arabic, transcribed) gets the stored briefing as ONE voice note —
    never a web search."""
    _prep(monkeypatch, tmp_path)
    dm_store.briefing.set("voice", True)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")),
        patch("backend.services.dm_media.transcribe_audio_bytes",
              new=AsyncMock(return_value="ابعت البريفينغ")),
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.telegram_tools._web_search",
              new=AsyncMock(return_value="search results")) as mock_search,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response_with_tools = AsyncMock(return_value="hallucinated")
        assert _webhook_voice_post("ابعت البريفينغ", update_id=1).status_code == 200
    mock_llm.get_response_with_tools.assert_not_called()
    mock_search.assert_not_called()
    mock_text.assert_not_called()
    mock_voice.assert_called_once()
    assert mock_voice.call_args.args[0] == FAKE_BRIEFING


@pytest.mark.asyncio
async def test_voice_note_briefing_request_without_voice_setting(
    monkeypatch, tmp_path,
):
    """A voice-note briefing request with the voice setting off still
    gets the stored briefing (as text) — the LLM still never runs."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")),
        patch("backend.services.dm_media.transcribe_audio_bytes",
              new=AsyncMock(return_value="الموجز")),
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.telegram_tools._web_search",
              new=AsyncMock(return_value="search results")) as mock_search,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response_with_tools = AsyncMock(return_value="hallucinated")
        assert _webhook_voice_post("الموجز", update_id=1).status_code == 200
    mock_llm.get_response_with_tools.assert_not_called()
    mock_search.assert_not_called()
    mock_voice.assert_not_called()
    mock_text.assert_called_once()
    assert mock_text.call_args.args[0] == FAKE_BRIEFING


# --- The negative: a plain news question is still a web search ---------


@pytest.mark.asyncio
async def test_plain_news_question_is_not_a_briefing(monkeypatch, tmp_path):
    """'what's the news in Jordan today' still reaches the LLM fallback
    — 'news' must never trigger the briefing path."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)),
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response_with_tools = AsyncMock(
            return_value="Here is the news."
        )
        assert _webhook_post(
            "what's the news in Jordan today", update_id=1,
        ).status_code == 200
    mock_llm.get_response_with_tools.assert_called_once()
    mock_text.assert_called_once_with("Here is the news.")


# --- The guard: settings changes still reach _handle_briefing ----------


@pytest.mark.asyncio
async def test_settings_change_still_reaches_briefing_handler(
    monkeypatch, tmp_path,
):
    """'make my briefing at 9am' with a briefing stored must move the
    time, not re-send the stored briefing."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
        patch("backend.scheduler.scheduler.schedule_cron",
              new=MagicMock()) as mock_cron,
    ):
        mock_llm.get_response_with_tools = AsyncMock(return_value="hallucinated")
        assert _webhook_post(
            "make my briefing at 9am", update_id=1,
        ).status_code == 200
    mock_llm.get_response_with_tools.assert_not_called()
    mock_cron.assert_called_once()
    mock_text.assert_called_once()
    assert "09:00" in mock_text.call_args.args[0]
    assert FAKE_BRIEFING not in mock_text.call_args.args[0]


def test_system_prompt_briefing_never_from_search():
    """Belt and braces: the system prompt says briefing requests are
    served from the stored briefing, never from a web search."""
    from backend.routers.router_telegram import _TELEGRAM_SYSTEM

    assert "send_briefing" in _TELEGRAM_SYSTEM
    assert "never from a web search" in _TELEGRAM_SYSTEM
    assert "never list sources for a briefing" in _TELEGRAM_SYSTEM
