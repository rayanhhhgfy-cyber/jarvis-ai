# ====================================================================
# JARVIS OMEGA — Telegram Notifier + Router Tests
# ====================================================================
"""
Tests for Jarvis talking to Sir on Telegram (the direct line), the
richer DM notifications, and the 'While you were away' activity feed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

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


# --- New webhook intents: tell / summarize / draft approval / activity ---

@pytest.mark.asyncio
async def test_telegram_webhook_tell_sends_dm(monkeypatch):
    """'tell Omar ...' sends a DM for Sir instead of chatting."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None

    async def _send_side_effect(name, text):
        # The greedy name regex first tries "Omar I" (not a contact);
        # the webhook retries with just "Omar".
        if name == "Omar I":
            return {"ok": False, "reason": "not_found"}
        return {"ok": True, "sender_name": "Omar Haddad", "platform": "messenger"}

    fake_responder.send_dm_to_name = AsyncMock(side_effect=_send_side_effect)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "tell Omar I will be there at 5"},
        })
    assert resp.status_code == 200
    fake_responder.send_dm_to_name.assert_awaited_with(
        "Omar", "I will be there at 5"
    )
    mock_llm.get_response.assert_not_called()
    mock_send.assert_called_once_with("Sent to Omar Haddad.")


@pytest.mark.asyncio
async def test_telegram_webhook_tell_unknown_person(monkeypatch):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.send_dm_to_name = AsyncMock(return_value={"ok": False, "reason": "not_found"})
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "tell Nobody hello"},
        })
    assert resp.status_code == 200
    mock_send.assert_called_once_with("I could not find a conversation with Nobody.")


@pytest.mark.asyncio
async def test_telegram_webhook_summarize(monkeypatch):
    """'summarize my conversation with Omar' returns a summary."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_activity = Mock(return_value=[
        {"sender_name": "Omar", "platform": "messenger", "text": "can we meet?",
         "reply": "Sure, when?", "important": False},
    ])
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(
            return_value="Omar asked to meet; you have not set a time yet."
        )
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "summarize my conversation with Omar"},
        })
    assert resp.status_code == 200
    mock_send.assert_called_once_with("Omar asked to meet; you have not set a time yet.")


@pytest.mark.asyncio
async def test_telegram_webhook_draft_approval_sends_draft(monkeypatch):
    """When a draft is pending, 'send' sends the draft as-is."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = {
        "thread_id": "t1", "draft_reply": "Let me check with Rayyan.",
        "sender_name": "Omar",
    }
    fake_responder.send_draft_reply = AsyncMock(return_value={
        "ok": True, "sender_name": "Omar", "platform": "messenger",
    })
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "send"},
        })
    assert resp.status_code == 200
    fake_responder.send_draft_reply.assert_awaited_once_with(
        "t1", "Let me check with Rayyan."
    )
    mock_llm.get_response.assert_not_called()
    mock_send.assert_called_once_with("Sent to Omar.")


@pytest.mark.asyncio
async def test_telegram_webhook_draft_approval_sends_own_text(monkeypatch):
    """When a draft is pending, Sir's own text is sent as the reply."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = {
        "thread_id": "t1", "draft_reply": "Let me check with Rayyan.",
        "sender_name": "Omar",
    }
    fake_responder.send_draft_reply = AsyncMock(return_value={
        "ok": True, "sender_name": "Omar", "platform": "messenger",
    })
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "Tell him I will call him tonight"},
        })
    assert resp.status_code == 200
    fake_responder.send_draft_reply.assert_awaited_once_with(
        "t1", "Tell him I will call him tonight"
    )
    mock_send.assert_called_once_with("Sent your reply to Omar.")


@pytest.mark.asyncio
async def test_telegram_webhook_includes_dm_activity_context(monkeypatch):
    """Normal chat includes recent DM activity so Sir can ask about his DMs."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_activity = Mock(return_value=[
        {"sender_name": "Layla", "platform": "instagram", "text": "the book arrived",
         "reply": "Great!", "important": False},
    ])
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)),
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="Layla said the book arrived.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "what did Layla say?"},
        })
    assert resp.status_code == 200
    call_kwargs = mock_llm.get_response.await_args.kwargs
    assert "Layla" in call_kwargs["user_message"]
    assert "the book arrived" in call_kwargs["user_message"]


# --- Abilities wave 2 webhook intents ---

@pytest.mark.asyncio
async def test_telegram_webhook_schedule_dm(monkeypatch):
    """'send Omar a message tomorrow at 5pm: ...' schedules a DM."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.schedule_dm.return_value = {"ok": True}
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "send Omar a message tomorrow at 5pm: I will be there"},
        })
    assert resp.status_code == 200
    fake_responder.schedule_dm.assert_called_once()
    args = fake_responder.schedule_dm.call_args.args
    assert args[0] == "Omar"
    assert args[1] == "I will be there"
    mock_send.assert_called_once()
    assert "Scheduled" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_remind_me(monkeypatch):
    """'remind me to call Omar tomorrow at 5pm' sets a reminder."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.add_reminder.return_value = {"ok": True}
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "remind me to call Omar tomorrow at 5pm"},
        })
    assert resp.status_code == 200
    fake_responder.add_reminder.assert_called_once()
    assert "call Omar" in fake_responder.add_reminder.call_args.args[0]
    assert "remind" in mock_send.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_telegram_webhook_remember(monkeypatch, tmp_path):
    """'remember that Omar loves football' stores a contact note."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "remember that Omar loves football"},
        })
    assert resp.status_code == 200
    assert "football" in dm_store.contacts.get("Omar", {}).get("notes", "")
    mock_send.assert_called_once()
    assert "Noted" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_busy_free(monkeypatch, tmp_path):
    """'I'm busy Friday 5pm-8pm' records a calendar entry."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "I'm busy Friday 5pm-8pm"},
        })
    assert resp.status_code == 200
    assert len(dm_store.calendar.all()) == 1
    assert "busy" in mock_send.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_telegram_webhook_unmute(monkeypatch):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.unmute_thread.return_value = True
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "unmute Omar"},
        })
    assert resp.status_code == 200
    fake_responder.unmute_thread.assert_called_once_with("Omar")
    assert "Unmuted" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_search(monkeypatch):
    """'find the message where Omar mentioned the book' searches DMs."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.search_dms = AsyncMock(return_value=[
        {"sender_name": "Omar", "platform": "instagram",
         "text": "the book is great", "reply": "Glad!"},
    ])
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "find the message where Omar mentioned the book"},
        })
    assert resp.status_code == 200
    fake_responder.search_dms.assert_awaited_once()
    assert "the book is great" in mock_send.call_args.args[0]


# --- Wave 3 webhook intents: rules + meeting times ---

@pytest.mark.asyncio
async def test_telegram_webhook_add_rule(monkeypatch, tmp_path):
    """'add a rule: if Omar asks about the club, reply ...' stores a rule."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.rules, "_path", tmp_path / "dm_rules.json")
    monkeypatch.setattr(dm_store.rules, "_loaded", False)
    monkeypatch.setattr(dm_store.rules, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "add a rule: if Omar asks about the club, reply here is the link"},
        })
    assert resp.status_code == 200
    all_rules = dm_store.rules.all()
    assert len(all_rules) == 1
    rule = next(iter(all_rules.values()))
    assert rule["person"] == "Omar"
    assert rule["topic"] == "the club"
    assert rule["reply"] == "here is the link"
    assert "Rule added" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_list_and_delete_rule(monkeypatch, tmp_path):
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.rules, "_path", tmp_path / "dm_rules.json")
    monkeypatch.setattr(dm_store.rules, "_loaded", False)
    monkeypatch.setattr(dm_store.rules, "_data", {})
    dm_store.rules.set("rule_1", {"person": "Omar", "topic": "club", "reply": "link"})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "list my rules"},
        })
    assert resp.status_code == 200
    assert "Omar" in mock_send.call_args.args[0]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "delete rule 1"},
        })
    assert resp.status_code == 200
    assert len(dm_store.rules.all()) == 0
    assert "Deleted" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_meeting_times(monkeypatch, tmp_path):
    """When a meeting awaits times, Sir's reply sends them to the person."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.meetings, "_path", tmp_path / "pending_meetings.json")
    monkeypatch.setattr(dm_store.meetings, "_loaded", False)
    monkeypatch.setattr(dm_store.meetings, "_data", {})
    dm_store.meetings.set("t1", {
        "platform": "messenger", "sender_name": "Omar",
        "offered": [], "awaiting_times": True,
    })
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None

    class _FakeClient:
        def __init__(self):
            self.sent = []

        async def send(self, thread_id, text):
            self.sent.append((thread_id, text))
            return {"ok": True}

    fake_client = _FakeClient()
    fake_responder._build_client.return_value = fake_client
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.load_connector",
              return_value={"method": "cookies", "data": {"cookies": {}}}),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "Friday 5pm or Saturday 10am"},
        })
    assert resp.status_code == 200
    assert len(fake_client.sent) == 1
    assert "Friday" in fake_client.sent[0][1]
    assert "Saturday" in fake_client.sent[0][1]
    meeting = dm_store.meetings.get("t1")
    assert meeting["awaiting_times"] is False
    assert len(meeting["offered"]) == 2


@pytest.mark.asyncio
async def test_telegram_webhook_birthday_message(monkeypatch, tmp_path):
    """'birthday message: ...' stores the custom birthday wish."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.settings, "_path", tmp_path / "dm_settings.json")
    monkeypatch.setattr(dm_store.settings, "_loaded", False)
    monkeypatch.setattr(dm_store.settings, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "birthday message: Happy birthday {name}, have a great one!"},
        })
    assert resp.status_code == 200
    assert dm_store.settings.get("birthday_message") == "Happy birthday {name}, have a great one!"
    assert "Saved" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_welcome_message(monkeypatch, tmp_path):
    """'group welcome message: ...' stores the custom group greeting."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.settings, "_path", tmp_path / "dm_settings.json")
    monkeypatch.setattr(dm_store.settings, "_loaded", False)
    monkeypatch.setattr(dm_store.settings, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "group welcome message: Hey {name}, welcome in!"},
        })
    assert resp.status_code == 200
    assert dm_store.settings.get("group_welcome_message") == "Hey {name}, welcome in!"
    assert "Saved" in mock_send.call_args.args[0]


# --- Slash commands: /start /help /send ... /activity /status /cancel ---

def _webhook_post(text: str, monkeypatch, fake_responder):
    """POST one Telegram webhook update from Sir; returns (resp, mock_send)."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    mock_send = AsyncMock(return_value=True)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=mock_send),
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": text},
        })
    return resp, mock_send, mock_llm


def test_remind_regex_keeps_tomorrow_at_5pm_together():
    """'tomorrow at 5pm' is one time expression, not thing + 'at 5pm'."""
    from backend.routers.router_telegram import _REMIND_RE

    m = _REMIND_RE.match("remind me to call Omar tomorrow at 5pm")
    assert m is not None
    assert m.group(1) == "call Omar"
    assert m.group(2) == "tomorrow at 5pm"
    m = _REMIND_RE.match("remind me to call Omar tomorrow")
    assert m.group(1) == "call Omar"
    assert m.group(2) == "tomorrow"
    m = _REMIND_RE.match("remind me to call Omar in 30 minutes")
    assert m.group(1) == "call Omar"
    assert m.group(2) == "in 30 minutes"
    m = _REMIND_RE.match("remind me to call Omar at 5pm")
    assert m.group(1) == "call Omar"
    assert m.group(2) == "at 5pm"


def test_normalize_command_translations():
    """Each slash command maps to its natural-language sentence."""
    from backend.routers.router_telegram import _normalize_command

    assert _normalize_command("/send Omar hi") == ("translate", "tell Omar hi")
    assert _normalize_command("/send@Jarvis_rayyan_bot Omar hi") == (
        "translate", "tell Omar hi")
    assert _normalize_command("/summarize Omar") == (
        "translate", "summarize conversation with Omar")
    assert _normalize_command("/schedule Omar tomorrow at 5pm: hi") == (
        "translate", "schedule Omar tomorrow at 5pm: hi")
    assert _normalize_command("/remind call Omar tomorrow at 5pm") == (
        "translate", "remind me to call Omar tomorrow at 5pm")
    assert _normalize_command("/busy Friday 5pm-8pm because practice") == (
        "translate", "I'm busy Friday 5pm-8pm because practice")
    assert _normalize_command("/free Saturday") == ("translate", "I'm free Saturday")
    assert _normalize_command("/remember Omar loves football") == (
        "translate", "remember Omar loves football")
    assert _normalize_command("/search book") == ("translate", "search book")
    assert _normalize_command("/search Omar | book") == (
        "translate", "find the message where Omar mentioned book")
    assert _normalize_command("/rules") == ("translate", "list my rules")
    assert _normalize_command("/addrule Omar | money | I'll check") == (
        "translate",
        "add a rule: if Omar asks about money, reply I'll check")
    assert _normalize_command("/delrule 2") == ("translate", "delete rule 2")
    assert _normalize_command("/unmute Omar") == ("translate", "unmute Omar")
    assert _normalize_command("/birthdaymsg Happy birthday {name}!") == (
        "translate", "birthday message: Happy birthday {name}!")
    assert _normalize_command("/welcomemsg Welcome {name}!") == (
        "translate", "group welcome message: Welcome {name}!")


def test_normalize_command_direct_usage_unknown():
    from backend.routers.router_telegram import _normalize_command

    assert _normalize_command("/start") == ("direct", "start")
    assert _normalize_command("/help") == ("direct", "help")
    assert _normalize_command("/activity") == ("direct", "activity")
    assert _normalize_command("/status") == ("direct", "status")
    assert _normalize_command("/cancel") == ("direct", "cancel")
    assert _normalize_command("/responder on") == ("direct", "responder")
    assert _normalize_command("/responder") == ("direct", "responder")
    assert _normalize_command("/connect instagram") == ("direct", "connect")
    assert _normalize_command("/disconnect instagram") == ("direct", "disconnect")
    assert _normalize_command("/send") == ("usage", "send")
    assert _normalize_command("/addrule Omar money") == ("usage", "addrule")
    assert _normalize_command("/frobnicate x") == ("unknown", "frobnicate")
    assert _normalize_command("hello") is None
    assert _normalize_command("tell Omar hi") is None


@pytest.mark.asyncio
async def test_telegram_webhook_start_and_help(monkeypatch):
    """'/start' welcomes Sir with the full command list; '/help' lists it."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    resp, mock_send, mock_llm = _webhook_post("/start", monkeypatch, fake_responder)
    assert resp.status_code == 200
    text = mock_send.call_args.args[0]
    assert "Hello Sir" in text
    assert "/send Omar" in text
    assert "/schedule" in text
    assert "/status" in text
    assert "/responder on" in text
    assert "/connect instagram" in text
    mock_llm.get_response.assert_not_called()
    resp, mock_send, mock_llm = _webhook_post("/help", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "/remind" in mock_send.call_args.args[0]
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_send(monkeypatch):
    """'/send Omar hi' sends the DM — same as 'tell Omar hi'."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.send_dm_to_name = AsyncMock(
        return_value={"ok": True, "sender_name": "Omar", "platform": "messenger"})
    resp, mock_send, mock_llm = _webhook_post("/send Omar hi", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.send_dm_to_name.assert_awaited_once_with("Omar", "hi")
    mock_llm.get_response.assert_not_called()
    assert mock_send.call_args.args[0] == "Sent to Omar."


@pytest.mark.asyncio
async def test_telegram_webhook_slash_schedule_and_remind(monkeypatch):
    """'/schedule ...' and '/remind ...' route to the scheduled/reminder stores."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.schedule_dm.return_value = {"ok": True}
    fake_responder.add_reminder.return_value = {"ok": True}
    resp, mock_send, _ = _webhook_post(
        "/schedule Omar tomorrow at 5pm: I will be there", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.schedule_dm.assert_called_once()
    assert fake_responder.schedule_dm.call_args.args[0] == "Omar"
    assert fake_responder.schedule_dm.call_args.args[1] == "I will be there"
    assert "Scheduled" in mock_send.call_args.args[0]
    resp, mock_send, _ = _webhook_post(
        "/remind call Omar tomorrow at 5pm", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.add_reminder.assert_called_once()
    assert fake_responder.add_reminder.call_args.args[0] == "call Omar"
    assert "remind" in mock_send.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_busy_remember(monkeypatch, tmp_path):
    """'/busy ...' and '/remember ...' write the calendar/contact stores."""
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    resp, mock_send, _ = _webhook_post(
        "/busy Friday 5pm-8pm", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert len(dm_store.calendar.all()) == 1
    assert "busy" in mock_send.call_args.args[0].lower()
    resp, mock_send, _ = _webhook_post(
        "/remember that Omar loves football", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "football" in dm_store.contacts.get("Omar", {}).get("notes", "")
    assert "Noted" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_slash_search(monkeypatch):
    """'/search book' searches all DMs; '/search Omar | book' scopes to Omar."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.search_dms = AsyncMock(return_value=[
        {"sender_name": "Omar", "platform": "instagram",
         "text": "the book is great", "reply": "Glad!"},
    ])
    resp, mock_send, _ = _webhook_post("/search book", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.search_dms.assert_awaited_once_with("book", name=None)
    assert "the book is great" in mock_send.call_args.args[0]
    fake_responder.search_dms.reset_mock()
    resp, mock_send, _ = _webhook_post("/search Omar | book", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.search_dms.assert_awaited_once_with("book", name="Omar")


@pytest.mark.asyncio
async def test_telegram_webhook_slash_rules(monkeypatch, tmp_path):
    """'/rules', '/addrule ...' and '/delrule 1' manage auto-reply rules."""
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.rules, "_path", tmp_path / "dm_rules.json")
    monkeypatch.setattr(dm_store.rules, "_loaded", False)
    monkeypatch.setattr(dm_store.rules, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    resp, mock_send, _ = _webhook_post(
        "/addrule Omar | money | I'll check with Rayyan", monkeypatch, fake_responder)
    assert resp.status_code == 200
    all_rules = dm_store.rules.all()
    assert len(all_rules) == 1
    rule = next(iter(all_rules.values()))
    assert rule["person"] == "Omar"
    assert rule["topic"] == "money"
    assert rule["reply"] == "I'll check with Rayyan"
    assert "Rule added" in mock_send.call_args.args[0]
    resp, mock_send, _ = _webhook_post("/rules", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "Omar" in mock_send.call_args.args[0]
    resp, mock_send, _ = _webhook_post("/delrule 1", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert len(dm_store.rules.all()) == 0
    assert "Deleted" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_slash_unmute_and_messages(monkeypatch, tmp_path):
    """'/unmute', '/birthdaymsg' and '/welcomemsg' work as commands."""
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.settings, "_path", tmp_path / "dm_settings.json")
    monkeypatch.setattr(dm_store.settings, "_loaded", False)
    monkeypatch.setattr(dm_store.settings, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.unmute_thread.return_value = True
    resp, mock_send, _ = _webhook_post("/unmute Omar", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.unmute_thread.assert_called_once_with("Omar")
    assert "Unmuted" in mock_send.call_args.args[0]
    resp, mock_send, _ = _webhook_post(
        "/birthdaymsg Happy birthday {name}!", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert dm_store.settings.get("birthday_message") == "Happy birthday {name}!"
    resp, mock_send, _ = _webhook_post(
        "/welcomemsg Welcome {name}!", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert dm_store.settings.get("group_welcome_message") == "Welcome {name}!"


@pytest.mark.asyncio
async def test_telegram_webhook_slash_activity(monkeypatch):
    """'/activity' lists recent DM exchanges; empty feed says so plainly."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_activity = Mock(return_value=[
        {"sender_name": "Layla", "platform": "instagram", "text": "the book arrived",
         "reply": "Great!", "important": False},
    ])
    resp, mock_send, mock_llm = _webhook_post("/activity", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "While you were away" in mock_send.call_args.args[0]
    assert "Layla" in mock_send.call_args.args[0]
    mock_llm.get_response.assert_not_called()
    fake_responder.get_activity = Mock(return_value=[])
    resp, mock_send, _ = _webhook_post("/activity", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "Nothing new" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_slash_status(monkeypatch):
    """'/status' reports the responder state and each platform's connection."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_status = Mock(return_value={
        "enabled": True, "running": True,
        "platforms": {
            "instagram": {"connected": False, "replied": 0, "last_error": None},
            "messenger": {"connected": False, "replied": 3, "last_error": None},
        },
    })
    resp, mock_send, mock_llm = _webhook_post("/status", monkeypatch, fake_responder)
    assert resp.status_code == 200
    text = mock_send.call_args.args[0]
    assert "DM responder: on, running" in text
    assert "instagram: not connected, 0 replies" in text
    assert "messenger: not connected, 3 replies" in text
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_unknown_and_usage(monkeypatch):
    """An unknown command gets a pointer to /help; a bare command gets usage."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    resp, mock_send, mock_llm = _webhook_post("/frobnicate x", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "don't know /frobnicate" in mock_send.call_args.args[0]
    assert "/help" in mock_send.call_args.args[0]
    mock_llm.get_response.assert_not_called()
    resp, mock_send, _ = _webhook_post("/send", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert mock_send.call_args.args[0] == "Usage: /send Omar I'll be there at 5"


@pytest.mark.asyncio
async def test_telegram_webhook_command_bypasses_pending_draft(monkeypatch):
    """A slash command is an instruction, never a draft reply — even when
    a tricky-message draft is waiting for Sir's approval."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = {
        "thread_id": "t1", "draft_reply": "Let me check with Rayyan.",
        "sender_name": "Omar",
    }
    fake_responder.send_draft_reply = AsyncMock(return_value={
        "ok": True, "sender_name": "Omar", "platform": "messenger",
    })
    fake_responder.send_dm_to_name = AsyncMock(
        return_value={"ok": True, "sender_name": "Omar", "platform": "messenger"})
    resp, mock_send, mock_llm = _webhook_post("/send Omar hi", monkeypatch, fake_responder)
    assert resp.status_code == 200
    fake_responder.send_draft_reply.assert_not_called()
    fake_responder.send_dm_to_name.assert_awaited_once_with("Omar", "hi")
    mock_llm.get_response.assert_not_called()
    assert mock_send.call_args.args[0] == "Sent to Omar."


def test_discard_pending_draft(tmp_path):
    """discard_pending_draft drops the newest draft and returns it."""
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    assert responder.discard_pending_draft() is None
    responder._pending_drafts = {
        "t1": {"thread_id": "t1", "sender_name": "Omar"},
        "t2": {"thread_id": "t2", "sender_name": "Layla"},
    }
    dropped = responder.discard_pending_draft()
    assert dropped["sender_name"] == "Layla"
    assert list(responder._pending_drafts) == ["t1"]
    assert responder.discard_pending_draft()["sender_name"] == "Omar"
    assert responder._pending_drafts == {}


@pytest.mark.asyncio
async def test_telegram_webhook_slash_cancel(monkeypatch, tmp_path):
    """'/cancel' drops a pending draft, or a pending meeting, or says so."""
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.meetings, "_path", tmp_path / "pending_meetings.json")
    monkeypatch.setattr(dm_store.meetings, "_loaded", False)
    monkeypatch.setattr(dm_store.meetings, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.discard_pending_draft.return_value = {
        "thread_id": "t1", "sender_name": "Omar",
    }
    resp, mock_send, _ = _webhook_post("/cancel", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "Cancelled" in mock_send.call_args.args[0]
    assert "Omar" in mock_send.call_args.args[0]
    fake_responder.discard_pending_draft.return_value = None
    dm_store.meetings.set("t1", {
        "platform": "messenger", "sender_name": "Layla",
        "offered": [], "awaiting_times": True,
    })
    resp, mock_send, _ = _webhook_post("/cancel", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "Cancelled the meeting request from Layla" in mock_send.call_args.args[0]
    assert dm_store.meetings.all() == {}
    resp, mock_send, _ = _webhook_post("/cancel", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert "Nothing is waiting" in mock_send.call_args.args[0]


# --- set_telegram_commands ---

@pytest.mark.asyncio
async def test_set_telegram_commands_ok(monkeypatch):
    """setMyCommands posts the full command list to Telegram."""
    import json

    from backend.services.telegram_notifier import (
        TELEGRAM_COMMANDS,
        set_telegram_commands,
    )

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    captured: dict[str, object] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    assert await set_telegram_commands(client=client) is True
    commands = captured["json"]["commands"]
    assert len(commands) == len(TELEGRAM_COMMANDS)
    assert commands[0] == {"command": "start", "description": "Start Jarvis and see all commands"}
    assert {c["command"] for c in commands} == {c["command"] for c in TELEGRAM_COMMANDS}
    assert all(set(c) == {"command", "description"} for c in commands)


@pytest.mark.asyncio
async def test_set_telegram_commands_no_token(monkeypatch):
    from backend.services.telegram_notifier import set_telegram_commands

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "")
    assert await set_telegram_commands(client=_mock_client()) is False


@pytest.mark.asyncio
async def test_set_telegram_commands_http_error(monkeypatch):
    from backend.services.telegram_notifier import set_telegram_commands

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    assert await set_telegram_commands(client=_mock_client(status=403)) is False


def test_telegram_status_reports_commands_registered(monkeypatch):
    """Status includes commands_registered (False until registration runs)."""
    monkeypatch.setattr("backend.config.settings.telegram_bot_token", "SECRET_TOKEN_123")
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "999")
    resp = _telegram_app().get("/api/telegram/status")
    assert resp.status_code == 200
    assert "commands_registered" in resp.json()
    assert "SECRET_TOKEN_123" not in resp.text


# --- /responder on/off ---

def _responder_post(text, monkeypatch, enabled, note=""):
    """POST a /responder update with mocked toggle state.

    Returns (resp, mock_send, mock_apply). ``enabled`` is the current
    toggle state; ``note`` is what apply_toggle reports on success.
    """
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    mock_send = AsyncMock(return_value=True)
    mock_apply = AsyncMock(return_value={
        "ok": True, "toggle_id": "dm_responder",
        "label": "DM responder", "enabled": not enabled, "note": note,
    })
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=mock_send),
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.system_toggles.get_state",
              return_value={"enabled": enabled, "detail": note}),
        patch("backend.services.system_toggles.apply_toggle", new=mock_apply),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": text},
        })
    return resp, mock_send, mock_apply, mock_llm


@pytest.mark.asyncio
async def test_telegram_webhook_slash_responder_on(monkeypatch):
    """'/responder on' turns the DM auto-replies on and reports the state."""
    resp, mock_send, mock_apply, mock_llm = _responder_post(
        "/responder on", monkeypatch, enabled=False,
        note="polling (instagram connected)",
    )
    assert resp.status_code == 200
    mock_apply.assert_awaited_once_with("dm_responder", True)
    assert mock_send.call_args.args[0] == (
        "DM responder is ON — polling (instagram connected)"
    )
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_responder_off(monkeypatch):
    """'/responder off' turns the DM auto-replies off."""
    resp, mock_send, mock_apply, mock_llm = _responder_post(
        "/responder off", monkeypatch, enabled=True,
        note="polling (instagram connected)",
    )
    assert resp.status_code == 200
    mock_apply.assert_awaited_once_with("dm_responder", False)
    assert mock_send.call_args.args[0] == (
        "DM responder is OFF — Jarvis will not auto-reply to DMs."
    )
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_responder_already(monkeypatch):
    """'/responder on' when already on changes nothing."""
    resp, mock_send, mock_apply, _ = _responder_post(
        "/responder on", monkeypatch, enabled=True,
        note="polling (instagram connected)",
    )
    assert resp.status_code == 200
    mock_apply.assert_not_called()
    assert "already ON" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_slash_responder_state(monkeypatch):
    """'/responder' alone reports the current state without changing it."""
    resp, mock_send, mock_apply, _ = _responder_post(
        "/responder", monkeypatch, enabled=True,
        note="polling (instagram connected)",
    )
    assert resp.status_code == 200
    mock_apply.assert_not_called()
    assert mock_send.call_args.args[0] == (
        "DM responder is ON — polling (instagram connected)"
    )
    resp, mock_send, mock_apply, _ = _responder_post(
        "/responder", monkeypatch, enabled=False, note="",
    )
    assert resp.status_code == 200
    mock_apply.assert_not_called()
    assert mock_send.call_args.args[0] == (
        "DM responder is OFF — Jarvis will not auto-reply to DMs."
    )


@pytest.mark.asyncio
async def test_telegram_webhook_slash_responder_usage(monkeypatch):
    """'/responder banana' gets the usage line, not a toggle change."""
    resp, mock_send, mock_apply, mock_llm = _responder_post(
        "/responder banana", monkeypatch, enabled=False, note="",
    )
    assert resp.status_code == 200
    mock_apply.assert_not_called()
    assert mock_send.call_args.args[0].startswith("Usage: /responder on")
    mock_llm.get_response.assert_not_called()


# --- /connect + /disconnect (cookies via Telegram, explicit only) ---

def _clear_pending_connect():
    """Drop any pending-connect state left by an earlier test."""
    from backend.routers import router_telegram

    router_telegram._pending_connect.pop("111", None)


@pytest.mark.asyncio
async def test_telegram_webhook_slash_connect_arms_wait(monkeypatch):
    """'/connect instagram' asks for the cookies as the next message."""
    from backend.routers import router_telegram

    _clear_pending_connect()
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    resp, mock_send, mock_llm = _webhook_post(
        "/connect instagram", monkeypatch, fake_responder)
    assert resp.status_code == 200
    assert router_telegram._pending_connect.get("111") == "instagram"
    assert "cookies" in mock_send.call_args.args[0].lower()
    mock_llm.get_response.assert_not_called()
    _clear_pending_connect()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_connect_usage(monkeypatch):
    """'/connect' with no/bad platform gets usage and arms nothing."""
    from backend.routers import router_telegram

    _clear_pending_connect()
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    for text in ("/connect", "/connect snapchat"):
        resp, mock_send, _ = _webhook_post(text, monkeypatch, fake_responder)
        assert resp.status_code == 200
        assert mock_send.call_args.args[0].startswith("Usage: /connect instagram")
        assert "111" not in router_telegram._pending_connect
    _clear_pending_connect()


@pytest.mark.asyncio
async def test_telegram_webhook_cookies_connect(monkeypatch):
    """Pasted cookies after /connect verify, store encrypted, wake the loop.

    The cookies never reach the LLM and are never echoed back.
    """
    from backend.routers import router_telegram

    _clear_pending_connect()
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.start = AsyncMock()
    fake_responder.get_status = Mock(return_value={"enabled": True})
    cookies_text = '[{"name": "sessionid", "value": "SECRET_COOKIE_VALUE"}]'
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.parse_cookies",
              return_value={"sessionid": "SECRET_COOKIE_VALUE"}) as mock_parse,
        patch("backend.services.dm_auth.verify_cookies",
              new=AsyncMock(return_value=True)) as mock_verify,
        patch("backend.services.dm_auth.save_connector") as mock_save,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        client = _telegram_app()
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/connect instagram"},
        })
        assert resp.status_code == 200
        assert router_telegram._pending_connect.get("111") == "instagram"
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": cookies_text},
        })
    assert resp.status_code == 200
    mock_parse.assert_called_once_with(cookies_text)
    mock_verify.assert_awaited_once_with(
        "instagram", {"sessionid": "SECRET_COOKIE_VALUE"})
    mock_save.assert_called_once_with(
        "instagram", "cookies", {"cookies": {"sessionid": "SECRET_COOKIE_VALUE"}})
    fake_responder.start.assert_awaited_once()
    assert mock_send.call_args.args[0] == (
        "Connected to Instagram. Jarvis will start replying to your Instagram DMs."
    )
    assert "SECRET_COOKIE_VALUE" not in mock_send.call_args.args[0]
    mock_llm.get_response.assert_not_called()
    assert "111" not in router_telegram._pending_connect
    _clear_pending_connect()


@pytest.mark.asyncio
async def test_telegram_webhook_cookies_bad_or_unverified(monkeypatch):
    """Unparseable or dead cookies store nothing and clear the wait."""
    from backend.routers import router_telegram

    _clear_pending_connect()
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.start = AsyncMock()
    fake_responder.get_status = Mock(return_value={"enabled": True})
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.parse_cookies",
              side_effect=ValueError("no cookies found")) as mock_parse,
        patch("backend.services.dm_auth.save_connector") as mock_save,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        client = _telegram_app()
        client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/connect instagram"},
        })
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "hello not cookies"},
        })
    assert resp.status_code == 200
    mock_parse.assert_called_once()
    mock_save.assert_not_called()
    assert "couldn't read" in mock_send.call_args.args[0]
    assert "111" not in router_telegram._pending_connect
    _clear_pending_connect()
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.parse_cookies",
              return_value={"sessionid": "stale"}),
        patch("backend.services.dm_auth.verify_cookies",
              new=AsyncMock(return_value=False)),
        patch("backend.services.dm_auth.save_connector") as mock_save,
    ):
        client = _telegram_app()
        client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/connect messenger"},
        })
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "c_user=1; xs=stale"},
        })
    assert resp.status_code == 200
    mock_save.assert_not_called()
    assert "didn't log in" in mock_send.call_args.args[0]
    assert "111" not in router_telegram._pending_connect
    _clear_pending_connect()


@pytest.mark.asyncio
async def test_telegram_webhook_paste_without_connect_goes_to_chat(monkeypatch):
    """A cookies-looking paste with no /connect first is just chat — the
    LLM answers it and no connect is attempted."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.parse_cookies") as mock_parse,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="What is this paste?")
        monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": '[{"name": "sessionid", "value": "abc"}]'},
        })
    assert resp.status_code == 200
    mock_parse.assert_not_called()
    mock_llm.get_response.assert_called_once()
    assert mock_send.call_args.args[0] == "What is this paste?"


@pytest.mark.asyncio
async def test_telegram_webhook_slash_disconnect(monkeypatch):
    """'/disconnect instagram' removes the stored credentials — and only
    this explicit command does."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.delete_connector",
              return_value=True) as mock_delete,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="should not be used")
        monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/disconnect instagram"},
        })
    assert resp.status_code == 200
    mock_delete.assert_called_once_with("instagram")
    assert mock_send.call_args.args[0] == (
        "Disconnected Instagram. Jarvis will stop replying to Instagram DMs. "
        "Reconnect any time with /connect instagram."
    )
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_slash_disconnect_not_connected(monkeypatch):
    """'/disconnect messenger' when nothing is connected says so."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.delete_connector",
              return_value=False),
    ):
        monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/disconnect messenger"},
        })
    assert resp.status_code == 200
    assert mock_send.call_args.args[0] == "Messenger isn't connected."


@pytest.mark.asyncio
async def test_telegram_webhook_slash_disconnect_usage(monkeypatch):
    """'/disconnect' with no/bad platform gets usage and deletes nothing."""
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_auth.delete_connector") as mock_delete,
    ):
        monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
        for text in ("/disconnect", "/disconnect snapchat"):
            resp = _telegram_app().post("/api/telegram/webhook", json={
                "message": {"chat": {"id": 111}, "text": text},
            })
            assert resp.status_code == 200
            assert mock_send.call_args.args[0].startswith(
                "Usage: /disconnect instagram")
    mock_delete.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_cancel_cancels_pending_connect(monkeypatch, tmp_path):
    """'/cancel' while a connect is waiting cancels the wait."""
    from backend.routers import router_telegram
    from backend.services import dm_store

    _clear_pending_connect()
    monkeypatch.setattr(dm_store.meetings, "_path", tmp_path / "pending_meetings.json")
    monkeypatch.setattr(dm_store.meetings, "_loaded", False)
    monkeypatch.setattr(dm_store.meetings, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.discard_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
        client = _telegram_app()
        client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/connect instagram"},
        })
        assert router_telegram._pending_connect.get("111") == "instagram"
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/cancel"},
        })
    assert resp.status_code == 200
    assert mock_send.call_args.args[0] == "Cancelled the Instagram connect."
    assert "111" not in router_telegram._pending_connect
    _clear_pending_connect()


@pytest.mark.asyncio
async def test_telegram_webhook_command_cancels_pending_connect(monkeypatch):
    """Any other command while a connect is waiting cancels the wait and
    the command itself still runs."""
    from backend.routers import router_telegram

    _clear_pending_connect()
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_status = Mock(return_value={
        "enabled": True, "running": False, "platforms": {},
    })
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
        client = _telegram_app()
        client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/connect instagram"},
        })
        assert router_telegram._pending_connect.get("111") == "instagram"
        resp = client.post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "/status"},
        })
    assert resp.status_code == 200
    assert "DM responder" in mock_send.call_args.args[0]
    assert "111" not in router_telegram._pending_connect
    _clear_pending_connect()


# --------------------------------------------------------------------
# Telegram voice messages (download + sendVoice)
# --------------------------------------------------------------------

def _telegram_file_handler(request: httpx.Request) -> httpx.Response:
    """getFile -> a file path; the file download -> fake OGG bytes."""
    if "getFile" in str(request.url):
        return httpx.Response(200, json={
            "ok": True, "result": {"file_path": "voice/file_1.ogg"},
        })
    return httpx.Response(200, content=b"fake-ogg-bytes")


@pytest.mark.asyncio
async def test_download_telegram_file_ok(monkeypatch):
    from backend.services.telegram_notifier import download_telegram_file

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "999")
    result = await download_telegram_file(
        "voice123",
        client=httpx.AsyncClient(transport=httpx.MockTransport(_telegram_file_handler)),
    )
    assert result == b"fake-ogg-bytes"


@pytest.mark.asyncio
async def test_download_telegram_file_getfile_fails(monkeypatch):
    from backend.services.telegram_notifier import download_telegram_file

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "999")
    assert await download_telegram_file("voice123", client=_mock_client(status=403)) is None


@pytest.mark.asyncio
async def test_download_telegram_file_not_configured(monkeypatch):
    from backend.services.telegram_notifier import download_telegram_file

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "")
    assert await download_telegram_file(
        "voice123", client=httpx.AsyncClient(transport=httpx.MockTransport(_telegram_file_handler))
    ) is None


@pytest.mark.asyncio
async def test_send_telegram_voice_ok(monkeypatch, tmp_path):
    """sendVoice posts the OGG file as multipart to Telegram."""
    from backend.services.telegram_notifier import send_telegram_voice

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "999")
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"fake-ogg-bytes")
    seen: dict[str, str | bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await send_telegram_voice(str(audio), client=client) is True
    assert "multipart/form-data" in str(seen["content_type"])
    assert b"voice.ogg" in bytes(seen["body"])


@pytest.mark.asyncio
async def test_send_telegram_voice_http_error(monkeypatch, tmp_path):
    from backend.services.telegram_notifier import send_telegram_voice

    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_bot_token", "tok123")
    monkeypatch.setattr("backend.services.telegram_notifier.settings.telegram_chat_id", "999")
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"fake-ogg-bytes")
    assert await send_telegram_voice(str(audio), client=_mock_client(status=403)) is False


# --------------------------------------------------------------------
# Telegram webhook: voice notes
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegram_webhook_voice_note_is_heard_and_answered_with_voice(monkeypatch):
    """A voice note to the bot is transcribed, answered, and the reply
    goes back as voice (not silently ignored)."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")) as mock_dl,
        patch("backend.services.dm_media.transcribe_audio_bytes",
              new=AsyncMock(return_value="what do you recommend")),
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)) as mock_voice,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="Here is what I recommend.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "voice": {"file_id": "voice123", "duration": 5}},
        })
    assert resp.status_code == 200
    mock_dl.assert_called_once_with("voice123")
    mock_llm.get_response.assert_called_once()
    assert "what do you recommend" in mock_llm.get_response.call_args.kwargs["user_message"]
    mock_voice.assert_called_once_with("Here is what I recommend.")
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_voice_note_unheard_falls_back_to_text(monkeypatch):
    """When a voice note cannot be transcribed, the bot says so in text
    instead of ignoring it — and never calls the LLM with nothing."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")),
        patch("backend.services.dm_media.transcribe_audio_bytes",
              new=AsyncMock(return_value=None)),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="hi")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "voice": {"file_id": "voice123", "duration": 5}},
        })
    assert resp.status_code == 200
    mock_llm.get_response.assert_not_called()
    mock_send.assert_called_once()
    assert "could not hear" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_telegram_webhook_voice_note_from_stranger_ignored(monkeypatch):
    """A voice note from anyone but Sir is ignored, like text."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")) as mock_dl,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="hi")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 999},
                        "voice": {"file_id": "voice123", "duration": 5}},
        })
    assert resp.status_code == 200
    mock_dl.assert_not_called()
    mock_send.assert_not_called()
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_voice_note_cancels_pending_connect(monkeypatch):
    """A voice note can never be cookies — while a connect is waiting,
    it cancels the wait and is answered as a normal message."""
    from backend.routers import router_telegram

    _clear_pending_connect()
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_activity.return_value = []
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)),
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")),
        patch("backend.services.dm_media.transcribe_audio_bytes",
              new=AsyncMock(return_value="hello jarvis")),
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=True)),
        patch("backend.services.llm_service.llm_service") as mock_llm,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        mock_llm.get_response = AsyncMock(return_value="Hi Sir.")
        router_telegram._pending_connect["111"] = "instagram"
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "voice": {"file_id": "voice123", "duration": 2}},
        })
    assert resp.status_code == 200
    assert "111" not in router_telegram._pending_connect
    mock_llm.get_response.assert_called_once()
    _clear_pending_connect()


@pytest.mark.asyncio
async def test_telegram_webhook_voice_reply_failure_falls_back_to_text(monkeypatch):
    """If the voice reply fails, the answer still arrives as text."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-ogg")),
        patch("backend.services.dm_media.transcribe_audio_bytes",
              new=AsyncMock(return_value="hello")),
        patch("backend.services.dm_voice.send_telegram_voice_reply",
              new=AsyncMock(return_value=False)),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="Hi Sir.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "voice": {"file_id": "voice123", "duration": 2}},
        })
    assert resp.status_code == 200
    mock_send.assert_called_once_with("Hi Sir.")


# --------------------------------------------------------------------
# Telegram system prompt: the bot knows what Jarvis really is
# --------------------------------------------------------------------

def test_telegram_system_prompt_knows_jarvis():
    """The bot's brain knows Rayyan, the real abilities, and what is
    already built — so it never suggests a duplicate or invents a place."""
    from backend.routers.router_telegram import _TELEGRAM_SYSTEM

    assert "Irbid" in _TELEGRAM_SYSTEM
    assert "Portland" not in _TELEGRAM_SYSTEM
    assert "Already built" in _TELEGRAM_SYSTEM
    assert "reminders" in _TELEGRAM_SYSTEM.lower()
    assert "voice-to-text" in _TELEGRAM_SYSTEM.lower()
    assert "/responder" in _TELEGRAM_SYSTEM
    assert "/connect" in _TELEGRAM_SYSTEM
    assert "phone calls" in _TELEGRAM_SYSTEM.lower()


# --------------------------------------------------------------------
# Telegram webhook: photos and videos
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegram_webhook_photo_is_seen_and_answered(monkeypatch):
    """A photo sent to the bot is described, and the bot answers about
    what is in it (not ignored, not a generic reply)."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-jpeg")) as mock_dl,
        patch("backend.services.dm_media.describe_image_bytes",
              new=AsyncMock(return_value="A cat sitting on a couch.")),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="That is a cat on a couch.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "photo": [{"file_id": "small"}, {"file_id": "big"}]},
        })
    assert resp.status_code == 200
    # The largest photo size is downloaded (last in the list).
    mock_dl.assert_called_once_with("big")
    mock_llm.get_response.assert_called_once()
    user_message = mock_llm.get_response.call_args.kwargs["user_message"]
    assert "[Photo: A cat sitting on a couch.]" in user_message
    mock_send.assert_called_once_with("That is a cat on a couch.")


@pytest.mark.asyncio
async def test_telegram_webhook_photo_with_caption_uses_caption(monkeypatch):
    """A photo with a caption: the caption is the question, the photo
    description is the context the bot answers from."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-jpeg")),
        patch("backend.services.dm_media.describe_image_bytes",
              new=AsyncMock(return_value="A cat sitting on a couch.")),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="It is a cat.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "photo": [{"file_id": "big"}],
                        "caption": "what animal is this?"},
        })
    assert resp.status_code == 200
    mock_llm.get_response.assert_called_once()
    user_message = mock_llm.get_response.call_args.kwargs["user_message"]
    assert "what animal is this?" in user_message
    assert "[Photo: A cat sitting on a couch.]" in user_message
    mock_send.assert_called_once_with("It is a cat.")


@pytest.mark.asyncio
async def test_telegram_webhook_video_is_seen_and_answered(monkeypatch):
    """A video sent to the bot is described from its frames and answered."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-mp4")) as mock_dl,
        patch("backend.services.dm_media.describe_video",
              new=AsyncMock(return_value="a dog running in a park")),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="That video shows a dog running.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "video": {"file_id": "vid123", "duration": 10}},
        })
    assert resp.status_code == 200
    mock_dl.assert_called_once_with("vid123")
    mock_llm.get_response.assert_called_once()
    user_message = mock_llm.get_response.call_args.kwargs["user_message"]
    assert "[Video: a dog running in a park]" in user_message
    mock_send.assert_called_once_with("That video shows a dog running.")


@pytest.mark.asyncio
async def test_telegram_webhook_photo_from_stranger_ignored(monkeypatch):
    """A photo from anyone but Sir is ignored, like text and voice."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-jpeg")) as mock_dl,
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="hi")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 999},
                        "photo": [{"file_id": "big"}]},
        })
    assert resp.status_code == 200
    mock_dl.assert_not_called()
    mock_send.assert_not_called()
    mock_llm.get_response.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_webhook_photo_unseen_still_answered(monkeypatch):
    """When a photo cannot be described, the bot still answers (saying
    it could not see it) instead of ignoring the message."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.telegram_notifier.download_telegram_file",
              new=AsyncMock(return_value=b"fake-jpeg")),
        patch("backend.services.dm_media.describe_image_bytes",
              new=AsyncMock(return_value=None)),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response = AsyncMock(return_value="I could not see that photo.")
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "photo": [{"file_id": "big"}]},
        })
    assert resp.status_code == 200
    mock_llm.get_response.assert_called_once()
    user_message = mock_llm.get_response.call_args.kwargs["user_message"]
    assert "I could not see this photo" in user_message
    mock_send.assert_called_once_with("I could not see that photo.")


@pytest.mark.asyncio
async def test_telegram_webhook_remind_clock_anywhere(monkeypatch):
    """'/remind i have a 4:05 appointment with the doctor' sets a
    reminder — the clock is in the middle, so _REMIND_RE misses it and
    without the fallback the chat would promise a reminder it never
    sets."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.add_reminder.return_value = {"ok": True}
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_time.parse_time") as mock_parse,
    ):
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        mock_parse.return_value = _dt(2026, 11, 10, 16, 5, tzinfo=_ZI("Asia/Amman"))
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "/remind i have a 4:05 appointment with the doctor"},
        })
    assert resp.status_code == 200
    fake_responder.add_reminder.assert_called_once()
    assert "doctor" in fake_responder.add_reminder.call_args.args[0]
    assert mock_send.call_args.args[0].startswith("Got it")


@pytest.mark.asyncio
async def test_telegram_webhook_remind_natural_language_clock_anywhere(monkeypatch):
    """'Hey I have an appointment with the doctor on 4:05 remind me of
    it please' sets a reminder — the same fallback, plain words."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.add_reminder.return_value = {"ok": True}
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.dm_time.parse_time") as mock_parse,
    ):
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        mock_parse.return_value = _dt(2026, 11, 10, 16, 5, tzinfo=_ZI("Asia/Amman"))
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111},
                        "text": "Hey I have an appointment with the doctor on 4:05 remind me of it please"},
        })
    assert resp.status_code == 200
    fake_responder.add_reminder.assert_called_once()
    assert "doctor" in fake_responder.add_reminder.call_args.args[0]
    assert mock_send.call_args.args[0].startswith("Got it")


@pytest.mark.asyncio
async def test_telegram_webhook_contact_lookup(monkeypatch, tmp_path):
    """'what is Omar's number?' answers from the saved contact card."""
    from backend.services import dm_store

    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    dm_store.contacts.set("Omar", {"phone": "+962788809843", "instagram": "omar.jo"})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "what is Omar's number?"},
        })
        assert resp.status_code == 200
        assert "+962788809843" in mock_send.call_args.args[0]
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "what is Omar's instagram?"},
        })
        assert resp.status_code == 200
        assert "@omar.jo" in mock_send.call_args.args[0]
        resp = _telegram_app().post("/api/telegram/webhook", json={
            "message": {"chat": {"id": 111}, "text": "what is Sara's number?"},
        })
        assert resp.status_code == 200
        assert "don't have" in mock_send.call_args.args[0]
