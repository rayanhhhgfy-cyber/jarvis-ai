# ====================================================================
# JARVIS OMEGA — Block command + durability tests
# ====================================================================
"""
Tests for the /block + /unblock commands and the "make him fantastic"
durability round (2026-11-11):

* /block stops Jarvis DMing a person until further notice; /unblock
  resumes. The block is stored in dm_store (Turso-backed), so it
  survives restarts and deploys, and it suppresses both DM replies
  and missed-call introductions.
* dm_store JsonStores mirror to Turso: a store whose local file is
  missing (fresh deploy) restores from Turso; a Turso outage falls
  back to the local file.
* Push subscriptions mirror to Turso the same way.
* GET /api/notifications/status reports subscription count + devices.
* Telegram webhook update_ids are deduplicated (no double replies).
* Briefing news retries a failed group query once.
* DM replies fall back from Groq 120b to Groq 20b before Gemini.
* The pending call reason lives for an hour, not fifteen minutes.

ALL credentials and endpoints here are FAKE. No real Turso database
is touched: the "server" is an in-memory fake behind
httpx.MockTransport speaking the Hrana /v2/pipeline shape.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import dm_store
from backend.services.dm_llm import generate_dm_reply
from backend.services.dm_responder import (
    _CALL_REASON_TTL_SECONDS,
    DMResponder,
    _fetch_briefing_news,
    dm_responder,
)

_FAKE_URL = "libsql://fake-host.turso.io"
_FAKE_TOKEN = "fake-turso-token"


class _FakeTurso:
    """In-memory stand-in for Turso's /v2/pipeline endpoint."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self.calls = 0
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(500, json={"error": "boom"}, request=request)
        body = json.loads(request.content.decode())
        results = []
        for req in body.get("requests", []):
            if req.get("type") == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = req.get("stmt", {})
            sql = stmt.get("sql", "")
            args = [a.get("value") for a in stmt.get("args", [])]
            rows, affected = self._run(sql, args)
            results.append({
                "type": "ok",
                "response": {"type": "execute", "result": {
                    "cols": [{"name": "key"}, {"name": "value"}],
                    "rows": [[{"type": "text", "value": v} for v in row] for row in rows],
                    "affected_row_count": affected,
                }},
            })
        return httpx.Response(200, json={"results": results}, request=request)

    def _run(self, sql: str, args: list[str]) -> tuple[list[tuple], int]:
        if sql.startswith("CREATE TABLE"):
            return [], 0
        if sql.startswith("SELECT"):
            return [(k, v) for k, v in self.rows.items()], 0
        if sql.startswith("INSERT OR REPLACE"):
            self.rows[args[0]] = args[1]
            return [], 1
        if sql.startswith("DELETE FROM"):
            if "NOT IN" in sql:
                keep = set(args)
                removed = [k for k in self.rows if k not in keep]
                for k in removed:
                    del self.rows[k]
                return [], len(removed)
            n = len(self.rows)
            self.rows.clear()
            return [], n
        raise AssertionError(f"unexpected SQL in fake Turso: {sql!r}")


def _set_turso_env(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.config.settings.turso_database_url", _FAKE_URL
    )
    monkeypatch.setattr(
        "backend.config.settings.turso_auth_token", _FAKE_TOKEN
    )


def _reset_dm_store_turso(monkeypatch, fake) -> None:
    """Point dm_store's Turso mirror at the fake and clear its cache."""
    _set_turso_env(monkeypatch)
    monkeypatch.setattr(dm_store, "_test_turso_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(dm_store, "_turso_clients", {})
    monkeypatch.setattr(dm_store, "_turso_ensured", set())


# --------------------------------------------------------------------
# /block + /unblock: responder methods
# --------------------------------------------------------------------

def _use_tmp_blocked_store(monkeypatch, tmp_path):
    monkeypatch.setattr(dm_store.blocked_users, "_path", tmp_path / "blocked_users.json")
    monkeypatch.setattr(dm_store.blocked_users, "_loaded", False)
    monkeypatch.setattr(dm_store.blocked_users, "_data", {})


def test_block_user_round_trip(monkeypatch, tmp_path):
    """block -> is_blocked True; unblock -> False; list shows names."""
    _use_tmp_blocked_store(monkeypatch, tmp_path)
    assert dm_responder.block_user("Omar") is True
    assert dm_responder.block_user("Omar") is False  # already blocked
    assert dm_responder.is_blocked("Omar") is True
    assert dm_responder.is_blocked("omar") is True  # case-insensitive
    assert dm_responder.is_blocked("Omar Aljamal") is True  # name contains
    assert dm_responder.is_blocked("Layla") is False
    assert dm_responder.list_blocked() == ["Omar"]
    assert dm_responder.unblock_user("Omar") is True
    assert dm_responder.unblock_user("Omar") is False  # already unblocked
    assert dm_responder.is_blocked("Omar") is False
    assert dm_responder.list_blocked() == []


def test_block_user_ignores_blank_name(monkeypatch, tmp_path):
    _use_tmp_blocked_store(monkeypatch, tmp_path)
    assert dm_responder.block_user("") is False
    assert dm_responder.block_user("   ") is False
    assert dm_responder.unblock_user("") is False


# --------------------------------------------------------------------
# /block + /unblock: Telegram commands
# --------------------------------------------------------------------

def _telegram_app():
    from backend.routers.router_telegram import router

    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


@pytest.mark.asyncio
async def test_webhook_block_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.block_user.return_value = True
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("/block Omar", update_id=11)
    assert resp.status_code == 200
    fake_responder.block_user.assert_called_once_with("Omar")
    assert "Blocked Omar" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_block_no_args_lists_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.list_blocked.return_value = ["Omar", "Layla"]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("/block", update_id=12)
    assert resp.status_code == 200
    fake_responder.list_blocked.assert_called_once()
    assert "Omar" in mock_send.call_args.args[0]
    assert "Layla" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_unblock_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.unblock_user.return_value = True
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("/unblock Omar", update_id=13)
    assert resp.status_code == 200
    fake_responder.unblock_user.assert_called_once_with("Omar")
    assert "Unblocked Omar" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_plain_block_text(monkeypatch, tmp_path):
    """'block Omar' without a slash works too."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.block_user.return_value = True
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("block Omar", update_id=14)
    assert resp.status_code == 200
    fake_responder.block_user.assert_called_once_with("Omar")
    assert "Blocked Omar" in mock_send.call_args.args[0]


def test_telegram_commands_include_block():
    """The bot menu lists /block and /unblock."""
    from backend.services.telegram_notifier import TELEGRAM_COMMANDS

    names = {c["command"] for c in TELEGRAM_COMMANDS}
    assert "block" in names
    assert "unblock" in names


# --------------------------------------------------------------------
# Blocked senders get no reply and no missed-call introduction
# --------------------------------------------------------------------

class _FakeClient:
    def __init__(self, user_id, messages):
        self.user_id = user_id
        self._messages = messages
        self.sent = []

    async def validate(self):
        return True

    async def list_recent(self, limit=10):
        return self._messages

    async def send(self, thread_id, text):
        self.sent.append((thread_id, text))
        return {"ok": True, "message_id": "sent-1"}


def _msg(thread_id, sender_id, sender_name, text, message_id, is_missed_call=False):
    return {
        "platform": "messenger", "thread_id": thread_id, "sender_id": sender_id,
        "sender_name": sender_name, "text": text, "message_id": message_id,
        "is_group": False, "is_missed_call": is_missed_call,
    }


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    """Point the connector vault at a temp file for the test."""
    from backend.services import dm_auth
    from backend.services.credentials_vault import CredentialsVault

    vault = CredentialsVault(storage_path=str(tmp_path / "connectors.json"))
    vault.initialize()
    monkeypatch.setattr(dm_auth, "connector_vault", vault)
    return vault


@pytest.mark.asyncio
async def test_blocked_sender_gets_no_reply(tmp_vault, monkeypatch, tmp_path):
    from backend.services import dm_auth

    _use_tmp_blocked_store(monkeypatch, tmp_path)
    dm_auth.save_connector("messenger", "cookies", {"cookies": {"c_user": "x"}})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    responder.block_user("Omar")
    fake = _FakeClient(user_id="111111", messages=[
        _msg("t1", "999", "Omar", "hello?", "m1"),
    ])
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None, last_reply=None):
        return {"ok": True, "reply": "hi!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    # A blocked sender never even enters the pending queue — the
    # blocked check runs before the one-minute wait logic — so one
    # poll is enough to prove no reply is sent.
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []


@pytest.mark.asyncio
async def test_blocked_missed_call_gets_no_introduction(tmp_vault, monkeypatch, tmp_path):
    from backend.services import dm_auth

    _use_tmp_blocked_store(monkeypatch, tmp_path)
    dm_auth.save_connector("messenger", "cookies", {"cookies": {"c_user": "x"}})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    responder.block_user("Omar")
    fake = _FakeClient(user_id="111111", messages=[
        _msg("t1", "999", "Omar", "", "m1", is_missed_call=True),
    ])
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None, last_reply=None):
        return {"ok": True, "reply": "hi, this is Jarvis!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []


# --------------------------------------------------------------------
# dm_store Turso mirror
# --------------------------------------------------------------------

def test_dm_store_restores_from_turso_when_local_missing(monkeypatch, tmp_path):
    """No local file (fresh deploy) -> the store comes back from Turso."""
    fake = _FakeTurso()
    _reset_dm_store_turso(monkeypatch, fake)
    # Seed Turso directly, as if a previous deploy had saved it.
    fake.rows["entry1"] = json.dumps({"text": "call Omar", "when": "2026-11-11T16:00:00"})
    store = dm_store.JsonStore("reminders.json")
    monkeypatch.setattr(store, "_path", tmp_path / "reminders.json")
    assert store.get("entry1") == {"text": "call Omar", "when": "2026-11-11T16:00:00"}
    # ...and the local file was refreshed from Turso.
    assert (tmp_path / "reminders.json").exists()


def test_dm_store_local_file_wins_over_turso(monkeypatch, tmp_path):
    """A local file that exists is trusted; stale Turso rows do not revive deleted keys."""
    fake = _FakeTurso()
    _reset_dm_store_turso(monkeypatch, fake)
    # Turso still holds a reminder that was already fired and deleted locally.
    fake.rows["old-entry"] = json.dumps({"text": "stale"})
    path = tmp_path / "reminders.json"
    path.write_text(json.dumps({"live-entry": {"text": "still here"}}), encoding="utf-8")
    store = dm_store.JsonStore("reminders.json")
    monkeypatch.setattr(store, "_path", path)
    assert store.get("live-entry") == {"text": "still here"}
    assert store.get("old-entry") is None


def test_dm_store_save_mirrors_to_turso(monkeypatch, tmp_path):
    """set() writes the local file AND the Turso row."""
    fake = _FakeTurso()
    _reset_dm_store_turso(monkeypatch, fake)
    store = dm_store.JsonStore("reminders.json")
    monkeypatch.setattr(store, "_path", tmp_path / "reminders.json")
    store.set("r1", {"text": "call Omar"})
    assert json.loads((tmp_path / "reminders.json").read_text(encoding="utf-8"))["r1"] == {"text": "call Omar"}
    assert "r1" in fake.rows
    assert json.loads(fake.rows["r1"]) == {"text": "call Omar"}


def test_dm_store_turso_down_falls_back_to_local(monkeypatch, tmp_path):
    """Turso 500s -> local file still works, no exception escapes."""
    fake = _FakeTurso()
    fake.fail = True
    _reset_dm_store_turso(monkeypatch, fake)
    store = dm_store.JsonStore("reminders.json")
    monkeypatch.setattr(store, "_path", tmp_path / "reminders.json")
    store.set("r1", {"text": "call Omar"})
    assert store.get("r1") == {"text": "call Omar"}
    assert fake.rows == {}


# --------------------------------------------------------------------
# Push subscriptions Turso mirror + /status endpoint
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_subscription_mirrors_to_turso(monkeypatch, tmp_path):
    from backend import notification_engine as engine_mod
    from backend.notification_engine import NotificationEngine

    fake = _FakeTurso()
    _set_turso_env(monkeypatch)
    monkeypatch.setattr(engine_mod, "_test_turso_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(engine_mod, "_turso_client", None)
    monkeypatch.setattr(engine_mod, "_turso_attempted", False)
    monkeypatch.setattr(engine_mod, "_turso_table_ready", False)
    engine = NotificationEngine(storage_dir=str(tmp_path))
    await engine.initialize()
    sub = {"endpoint": "https://web.push.apple.com/fake", "keys": {"p256dh": "x", "auth": "y"}}
    await engine.save_subscription("jarvis-call", sub)
    assert "jarvis-call" in fake.rows
    assert json.loads(fake.rows["jarvis-call"]) == sub


@pytest.mark.asyncio
async def test_push_subscription_restores_from_turso(monkeypatch, tmp_path):
    from backend import notification_engine as engine_mod
    from backend.notification_engine import NotificationEngine

    fake = _FakeTurso()
    _set_turso_env(monkeypatch)
    monkeypatch.setattr(engine_mod, "_test_turso_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(engine_mod, "_turso_client", None)
    monkeypatch.setattr(engine_mod, "_turso_attempted", False)
    monkeypatch.setattr(engine_mod, "_turso_table_ready", False)
    # Seed Turso as if a previous deploy had saved the subscription.
    sub = {"endpoint": "https://web.push.apple.com/fake", "keys": {"p256dh": "x", "auth": "y"}}
    fake.rows["jarvis-call"] = json.dumps(sub)
    engine = NotificationEngine(storage_dir=str(tmp_path / "fresh"))
    await engine.initialize()
    assert engine.subscription_count() == 1
    assert engine.subscription_device_ids() == ["jarvis-call"]


def test_push_status_endpoint(monkeypatch):
    from backend import notification_engine as engine_mod

    monkeypatch.setattr(
        "backend.config.settings.vapid_public_key",
        "BH9o6l0BZD7zb84G9uJEdSN4Ig",
    )
    monkeypatch.setattr(
        "backend.config.settings.vapid_private_key", "",
    )
    with TestClient(app) as client:
        # Startup reloads subscriptions from disk, so set the fake
        # subscription AFTER the app is up, just before the request.
        monkeypatch.setattr(
            engine_mod.notification_engine, "_subscriptions",
            {"jarvis-call": {"endpoint": "https://web.push.apple.com/fake", "keys": {}}},
        )
        resp = client.get("/api/notifications/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subscriptions"] == 1
    assert body["devices"] == ["jarvis-call"]
    assert body["public_key_prefix"] == "BH9o6l0BZD7z"
    assert body["configured"] is False


# --------------------------------------------------------------------
# Telegram webhook update_id dedup
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_duplicate_update_id_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.unmute_thread.return_value = True
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp1 = _webhook_post("unmute Omar", update_id=99)
        resp2 = _webhook_post("unmute Omar", update_id=99)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # The update was processed once — one reply, not two.
    assert mock_send.call_count == 1


# --------------------------------------------------------------------
# Briefing news retries a failed group query once
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_briefing_news_retries_failed_group(monkeypatch):
    from backend.services import web_search_service as search_mod

    calls: dict[str, int] = {}

    async def fake_search(self, query, max_results=2):
        calls[query] = calls.get(query, 0) + 1
        if calls[query] == 1:
            return []  # first attempt: flaky backend, nothing back
        return [
            {"title": f"Headline for {query}", "snippet": "s", "url": "https://example.com"},
            {"title": f"Second for {query}", "snippet": "s", "url": "https://example.com/2"},
        ]

    monkeypatch.setattr(search_mod.WebSearchService, "search", fake_search)
    headlines = await _fetch_briefing_news("en")
    # 4 groups x 2 headlines, all recovered on the retry.
    assert len(headlines) == 8
    assert all(h["title"] for h in headlines)
    assert sum(calls.values()) == 8  # 4 first attempts + 4 retries


# --------------------------------------------------------------------
# DM replies fall back from Groq 120b to Groq 20b
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dm_llm_falls_back_to_groq_20b(monkeypatch):
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr("backend.services.dm_llm.settings.gemini_api_key", "")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if body.get("model") == "openai/gpt-oss-120b":
            return httpx.Response(429, json={"error": {"message": "rate limited"}}, request=request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "أهلاً! كيف أقدر أساعدك؟"}}],
        }, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await generate_dm_reply("messenger", "Friend", "مرحبا", client=client)
    assert result["ok"] is True
    assert result["model"] == "groq"
    assert "أهلاً" in result["reply"]


# --------------------------------------------------------------------
# Call reason lives an hour
# --------------------------------------------------------------------

def test_call_reason_ttl_is_one_hour():
    assert _CALL_REASON_TTL_SECONDS == 3600
