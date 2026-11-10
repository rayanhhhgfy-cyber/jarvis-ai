# ====================================================================
# JARVIS OMEGA — Telegram Notifier + Router Tests
# ====================================================================
"""
Tests for Jarvis talking to Sir on Telegram (the direct line), the
richer DM notifications, and the 'While you were away' activity feed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.router_connectors import router as connectors_router
from backend.routers.router_telegram import router as telegram_router
from backend.services.dm_responder import DMResponder
from backend.services.telegram_notifier import (
    send_telegram_message,
    set_telegram_webhook,
)


def _mock_client(status: int = 200, body: dict | None = None) -> httpx.AsyncClient:
    """httpx client whose every POST returns the given Telegram-style body."""
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


# --------------------------------------------------------------------
# telegram_notifier
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_telegram_message_ok(monkeypatch):
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "999")
    assert await send_telegram_message("hello", client=_mock_client()) is True


@pytest.mark.asyncio
async def test_send_telegram_message_not_configured(monkeypatch):
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "")
    assert await send_telegram_message("hello", client=_mock_client()) is False


@pytest.mark.asyncio
async def test_send_telegram_message_http_error(monkeypatch):
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "999")
    assert await send_telegram_message("hello", client=_mock_client(status=403)) is False


@pytest.mark.asyncio
async def test_set_telegram_webhook_ok(monkeypatch):
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    assert await set_telegram_webhook(client=_mock_client()) is True


@pytest.mark.asyncio
async def test_set_telegram_webhook_no_token(monkeypatch):
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "")
    assert await set_telegram_webhook(client=_mock_client()) is False


# --------------------------------------------------------------------
# DM activity feed
# --------------------------------------------------------------------

def test_record_activity_caps_at_20(tmp_path):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    for i in range(25):
        responder._record_activity(
            "instagram",
            {"sender_name": f"Friend {i}", "text": f"hi {i}"},
            f"reply {i}",
            important=False,
        )
    activity = responder.get_activity()
    assert len(activity) == 20
    assert activity[0]["sender_name"] == "Friend 24"  # newest first
    assert activity[0]["reply"] == "reply 24"
    assert activity[-1]["sender_name"] == "Friend 5"


@pytest.mark.asyncio
async def test_notify_new_dm_records_activity_with_reply(tmp_path):
    """_notify_new_dm records the exchange (push/Telegram fail silently)."""
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    await responder._notify_new_dm(
        "messenger",
        {"sender_name": "Omar", "text": "is the meeting tomorrow?", "thread_id": "t1"},
        important=True,
        reply="Yes, tomorrow at 5. Rayyan will confirm.",
    )
    activity = responder.get_activity()
    assert len(activity) == 1
    entry = activity[0]
    assert entry["sender_name"] == "Omar"
    assert entry["text"] == "is the meeting tomorrow?"
    assert entry["reply"] == "Yes, tomorrow at 5. Rayyan will confirm."
    assert entry["important"] is True
    assert entry["platform"] == "messenger"


def test_dm_activity_endpoint():
    """GET /api/connectors/dm/activity returns the responder's feed."""
    from backend.services.dm_responder import dm_responder

    dm_responder._activity = [{
        "time": "2026-11-10T05:00:00+00:00",
        "platform": "instagram",
        "sender_name": "Layla",
        "text": "hello",
        "reply": "Hi, this is Jarvis.",
        "important": False,
        "is_group": False,
    }]
    app = FastAPI()
    app.include_router(connectors_router)
    with TestClient(app) as client:
        resp = client.get("/api/connectors/dm/activity")
    assert resp.status_code == 200
    assert resp.json()["activity"][0]["sender_name"] == "Layla"
    dm_responder._activity = []


# --------------------------------------------------------------------
# Telegram router
# --------------------------------------------------------------------

def _telegram_app() -> TestClient:
    app = FastAPI()
    app.include_router(telegram_router)
    return TestClient(app)


def test_telegram_status_never_leaks_token(monkeypatch):
    """Status reports only booleans — the token value never appears."""
    monkeypatch.setattr("backend.config.settings.telegram_bot_token", "SECRET_TOKEN_123")
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "999")
    resp = _telegram_app().get("/api/telegram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["bot_token_set"] is True
    assert "SECRET_TOKEN_123" not in resp.text


@pytest.mark.asyncio
async def test_telegram_webhook_ignores_strangers(monkeypatch):
    """A message from anyone but Sir is ignored (no LLM call, no reply)."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="hi")
        client = _telegram_app()
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 999}, "text": "hello"},
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_send.assert_not_called()
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_answers_sir(monkeypatch):
    """A message from Sir's chat id gets an LLM reply sent back."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="Of course, Sir.")
        client = _telegram_app()
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "what did Omar ask?"},
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_llm.get_response.assert_called_once()
    mock_send.assert_called_once_with("Of course, Sir.")


@pytest.mark.asyncio
async def test_telegram_test_endpoint_not_configured(monkeypatch):
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "")
    resp = _telegram_app().post("/api/telegram/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
