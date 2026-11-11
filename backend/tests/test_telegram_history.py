# ====================================================================
# JARVIS OMEGA — Telegram conversation history tests (2026-11-11)
# ====================================================================
"""
Sir's order: "The cat's brain should recognize commands and talking
just like I sent it." The brain had NO memory of the conversation —
every message reached the LLM alone, so "Nope I want it now" meant
nothing and the brain guessed Instagram. Now the recent turns are
recorded and passed to the LLM as chat_history, so "it" / "that" /
"today" resolve to what was just said.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import router_telegram
from backend.routers.router_telegram import (
    _get_telegram_history,
    _looks_like_secret,
    _record_turn,
)
from backend.services import dm_store


def _telegram_app():
    test_app = FastAPI()
    test_app.include_router(router_telegram.router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


def _prep(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    monkeypatch.setattr(dm_store.telegram_history, "_path", tmp_path / "telegram_history.json")
    monkeypatch.setattr(dm_store.telegram_history, "_loaded", False)
    monkeypatch.setattr(dm_store.telegram_history, "_data", {})
    monkeypatch.setattr(dm_store.briefing, "_path", tmp_path / "briefing.json")
    monkeypatch.setattr(dm_store.briefing, "_loaded", False)
    monkeypatch.setattr(dm_store.briefing, "_data", {})


def _responder():
    fake = MagicMock()
    fake.get_pending_draft.return_value = None
    return fake


def test_record_and_read_history(monkeypatch, tmp_path):
    """Turns are recorded in order and read back oldest-first."""
    _prep(monkeypatch, tmp_path)
    _record_turn("user", "send it as a voice note")
    _record_turn("assistant", "Your morning briefing will arrive as a voice note from tomorrow.")
    _record_turn("user", "Nope I want it now")
    history = _get_telegram_history()
    assert len(history) == 3
    assert history[0] == {"role": "user", "content": "send it as a voice note"}
    assert history[1]["role"] == "assistant"
    assert "voice note" in history[1]["content"]
    assert history[2] == {"role": "user", "content": "Nope I want it now"}


def test_history_caps_at_40(monkeypatch, tmp_path):
    """The history never grows past 40 messages."""
    _prep(monkeypatch, tmp_path)
    for i in range(50):
        _record_turn("user", f"message {i}")
    history = _get_telegram_history()
    assert len(history) == 40
    assert history[0]["content"] == "message 10"
    assert history[-1]["content"] == "message 49"


def test_secrets_never_recorded(monkeypatch, tmp_path):
    """Cookies, tokens and cookie dumps never land in the history."""
    assert _looks_like_secret('[{"name": "sessionid", "value": "abc"}]')
    assert _looks_like_secret("sessionid=abc123; csrftoken=xyz")
    assert _looks_like_secret("#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t123\tsessionid\tabc")
    assert not _looks_like_secret("send it as a voice note")
    assert not _looks_like_secret("No I want today the one you gave me today")
    _prep(monkeypatch, tmp_path)
    _record_turn("user", '[{"name": "sessionid", "value": "abc"}]')
    _record_turn("user", "hello")
    assert _get_telegram_history() == [
        {"role": "user", "content": "hello"}
    ]


@pytest.mark.asyncio
async def test_llm_gets_conversation_history(monkeypatch, tmp_path):
    """The LLM fallback receives the recent turns, so 'it' resolves."""
    _prep(monkeypatch, tmp_path)
    # A first exchange: the bot told him the briefing comes as voice
    # tomorrow. That reply is recorded by the send wrapper.
    with (
        patch("backend.routers.router_telegram._send_telegram_message_raw",
              new=AsyncMock(return_value=True)),
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="ok")
        assert _webhook_post("/briefing voice", update_id=1).status_code == 200
        # The bot's reply is in the history now.
        assert any(
            "voice note from tomorrow" in m["content"]
            for m in _get_telegram_history()
        )
        # His next message is free chat (no handler matches it), so it
        # reaches the LLM — with that history attached.
        assert _webhook_post("why tomorrow and not today?", update_id=2).status_code == 200
    assert mock_llm.get_response.called
    _, kwargs = mock_llm.get_response.call_args
    history = kwargs.get("chat_history") or []
    assert any("voice note from tomorrow" in m["content"] for m in history)
    assert any(m["content"] == "why tomorrow and not today?" for m in history)


@pytest.mark.asyncio
async def test_send_wrapper_records_reply(monkeypatch, tmp_path):
    """Every bot reply is recorded through the send wrapper."""
    _prep(monkeypatch, tmp_path)
    with patch(
        "backend.routers.router_telegram._send_telegram_message_raw",
        new=AsyncMock(return_value=True),
    ) as mock_raw:
        assert await router_telegram.send_telegram_message("hello sir") is True
    mock_raw.assert_called_once_with("hello sir")
    assert _get_telegram_history() == [
        {"role": "assistant", "content": "hello sir"}
    ]
