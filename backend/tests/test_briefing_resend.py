# ====================================================================
# JARVIS OMEGA — briefing resend tests (2026-11-11)
# ====================================================================
"""
Regression tests for the screenshot Rayyan sent on 2026-11-11 10:11:
he asked for the morning briefing "in a beautiful format" and "as a
voice note", and the bot (1) replied in text, (2) INVENTED a schedule,
birthdays and DMs that were never in the real briefing, and (3) when
he said "send it to me the full thing no deletion in a voice note",
asked which Instagram conversation he meant.

The fix: the exact briefing text is stored when it goes out, and a
resend request re-sends THAT text (as voice when asked) — the LLM is
never asked to reproduce it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import router_telegram
from backend.services import dm_store

FAKE_BRIEFING = (
    "☀️ Good morning, Rayyan! — Tuesday, November 11\n"
    "🌤️ Weather in Irbid: Clear skies, 22°C\n"
    "📅 Nothing on your calendar today."
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


def _prep(monkeypatch, tmp_path, briefing_text=FAKE_BRIEFING):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    monkeypatch.setattr(dm_store.briefing, "_path", tmp_path / "briefing.json")
    monkeypatch.setattr(dm_store.briefing, "_loaded", False)
    monkeypatch.setattr(dm_store.briefing, "_data", {})
    if briefing_text is not None:
        dm_store.briefing.set(
            "last_sent",
            {
                "text": briefing_text,
                "sent_at": "2026-11-11T07:00:00+00:00",
                "language": "en",
            },
        )


def _responder():
    fake = MagicMock()
    fake.get_pending_draft.return_value = None
    return fake


@pytest.mark.asyncio
async def test_resend_beautiful_format_as_voice(monkeypatch, tmp_path):
    """His exact first message: format + resend as a voice note."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="hallucinated")
        assert _webhook_post(
            "Put it in a beautiful format and resend it as a voice note in English",
            update_id=1,
        ).status_code == 200
    # The stored briefing went out as a voice note — the LLM never ran.
    mock_voice.assert_called_once()
    assert mock_voice.call_args.args[0] == FAKE_BRIEFING
    mock_llm.get_response.assert_not_called()
    mock_text.assert_not_called()
    # Nothing invented: no fake schedule, no fake birthdays, no fake DMs.
    assert "Math class" not in mock_voice.call_args.args[0]
    assert "Omar" not in mock_voice.call_args.args[0]
    assert "sara_lee" not in mock_voice.call_args.args[0]


@pytest.mark.asyncio
async def test_resend_full_thing_no_deletion_as_voice(monkeypatch, tmp_path):
    """His exact second message: the full thing, no deletion, voice."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="which conversation?")
        assert _webhook_post(
            "Send it to me the full thing no deletion in a voice note",
            update_id=1,
        ).status_code == 200
    mock_voice.assert_called_once()
    assert mock_voice.call_args.args[0] == FAKE_BRIEFING
    mock_llm.get_response.assert_not_called()
    mock_text.assert_not_called()


@pytest.mark.asyncio
async def test_bare_voice_note_resends_briefing(monkeypatch, tmp_path):
    """His third message: just "Voice note" after the briefing."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("Voice note", update_id=1).status_code == 200
    mock_voice.assert_called_once()
    assert mock_voice.call_args.args[0] == FAKE_BRIEFING
    mock_text.assert_not_called()


@pytest.mark.asyncio
async def test_resend_text_when_no_voice_asked(monkeypatch, tmp_path):
    """A resend without "voice" comes back as the stored text."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("resend it", update_id=1).status_code == 200
    mock_voice.assert_not_called()
    mock_text.assert_called_once()
    assert mock_text.call_args.args[0] == FAKE_BRIEFING


@pytest.mark.asyncio
async def test_resend_without_stored_briefing(monkeypatch, tmp_path):
    """No briefing stored yet: a clear answer, not a hallucination."""
    _prep(monkeypatch, tmp_path, briefing_text=None)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_text,
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="hallucinated")
        assert _webhook_post("resend it as a voice note", update_id=1).status_code == 200
    mock_voice.assert_not_called()
    mock_llm.get_response.assert_not_called()
    assert "don't have a briefing" in mock_text.call_args.args[0]


@pytest.mark.asyncio
async def test_send_person_a_voice_note_is_not_a_resend(monkeypatch, tmp_path):
    """'Send Omar a voice note' must not resend the briefing."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="ok")
        assert _webhook_post("send Omar a voice note", update_id=1).status_code == 200
    mock_voice.assert_not_called()


@pytest.mark.asyncio
async def test_briefing_voice_now_sends_now(monkeypatch, tmp_path):
    """'Send my briefing as a voice note' sends it NOW, not tomorrow."""
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch(
            "backend.services.dm_responder.dm_responder.send_morning_briefing",
            new=AsyncMock(return_value=True),
        ) as mock_send,
    ):
        reply = await router_telegram._handle_briefing(
            "send my briefing as a voice note"
        )
    mock_send.assert_called_once()
    assert "voice note" in reply.lower()
    assert "tomorrow" not in reply.lower()


@pytest.mark.asyncio
async def test_briefing_voice_alone_only_sets_setting(monkeypatch, tmp_path):
    """A bare 'voice' setting change still just sets it for tomorrow."""
    _prep(monkeypatch, tmp_path)
    with patch(
        "backend.services.dm_responder.dm_responder.send_morning_briefing",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        reply = await router_telegram._handle_briefing("/briefing voice")
    mock_send.assert_not_called()
    assert "tomorrow" in reply.lower()


@pytest.mark.asyncio
async def test_send_morning_briefing_stores_text(monkeypatch, tmp_path):
    """The briefing that goes out is stored verbatim for resends."""
    from backend.services.dm_responder import dm_responder

    _prep(monkeypatch, tmp_path, briefing_text=None)
    with (
        patch("backend.services.dm_responder._fetch_irbid_weather",
              new=AsyncMock(return_value=None)),
        patch("backend.services.dm_responder._fetch_briefing_news",
              new=AsyncMock(return_value=[])),
        patch("backend.services.telegram_notifier.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
    ):
        assert await dm_responder.send_morning_briefing() is True
    sent = mock_send.call_args.args[0]
    stored = dm_store.briefing.get("last_sent")
    assert stored is not None
    assert stored["text"] == sent
    assert "Nothing on your calendar today" in stored["text"]
