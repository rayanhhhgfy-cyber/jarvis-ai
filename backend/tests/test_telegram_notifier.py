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
