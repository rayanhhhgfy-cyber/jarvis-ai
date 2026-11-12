# ====================================================================
# JARVIS OMEGA — low-automation-footprint tests
# ====================================================================
"""
Tests for the 2026-11-12 footprint reduction (after Instagram's "we
suspect automated behavior" warning): jittered polling, reply pacing
with an hourly cap, one long-lived client per platform, no per-poll
session validation, and a durable Instagram warning lockout that
stops polling until Sir reconnects.

ALL data here is fake. No real login is attempted, and the responder
is never started against a real account.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services import dm_responder as dm_resp
from backend.services import dm_store
from backend.services.dm_responder import (
    DMResponder,
    _is_instagram_warning,
)


# A ChallengeRequired-shaped error, as instagrapi raises it.
class ChallengeRequired(Exception):
    pass


class FeedbackRequired(Exception):
    pass


@pytest.fixture
def tmp_warning_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dm_store.instagram_warning, "_path", tmp_path / "instagram_warning.json"
    )
    monkeypatch.setattr(dm_store.instagram_warning, "_loaded", False)
    monkeypatch.setattr(dm_store.instagram_warning, "_data", {})
    return dm_store.instagram_warning


@pytest.fixture
def real_gaps(monkeypatch):
    """Restore the production pacing values (conftest zeroes them)."""
    monkeypatch.setattr(dm_resp, "_MIN_GLOBAL_REPLY_GAP_SECONDS", 20.0)
    monkeypatch.setattr(dm_resp, "_MIN_THREAD_REPLY_GAP_SECONDS", 60.0)
    monkeypatch.setattr(dm_resp, "_MAX_AUTO_REPLIES_PER_HOUR", 20)


class _FakeIGClient:
    """Fake Instagram client: sync validate, async list/send."""

    def __init__(self, messages=None, list_error=None):
        self._messages = list(messages or [])
        self._list_error = list_error
        self.user_id = "111"
        self.validate_calls = 0
        self.list_calls = 0
        self.sent: list[tuple[str, str]] = []

    def validate(self):
        self.validate_calls += 1
        return True

    async def list_recent(self, limit=10):
        self.list_calls += 1
        if self._list_error is not None:
            raise self._list_error
        return list(self._messages)

    async def send(self, thread_id, text):
        self.sent.append((thread_id, text))
        return {"ok": True, "message_id": "sent-1"}


def _wire_instagram(monkeypatch, responder, fake, blob=None):
    """Route poll_once at a fake Instagram client only."""
    blob = blob or {"method": "cookies", "data": {"cookies": {"sessionid": "x"}}}
    monkeypatch.setattr(
        dm_resp.dm_auth, "connector_status",
        lambda p: {"connected": p == "instagram"},
    )
    monkeypatch.setattr(
        dm_resp.dm_auth, "load_connector",
        lambda p: blob if p == "instagram" else None,
    )
    monkeypatch.setattr(
        responder, "_build_client", lambda platform, method, data: fake
    )


# --------------------------------------------------------------------
# Poll interval + jitter
# --------------------------------------------------------------------


def test_poll_interval_default_is_120():
    """Before: 60s. After: 120s base (plus jitter)."""
    assert dm_resp.settings.dm_poll_interval_seconds == 120


def test_next_poll_delay_jitter_range(monkeypatch):
    """Base 120s plus a random 0–60s: never a rigid 120-second beat."""
    monkeypatch.setattr(dm_resp.random, "uniform", lambda a, b: 0.0)
    responder = DMResponder(seen_path="/tmp/nope.json")
    assert responder._next_poll_delay() == 120.0
    monkeypatch.setattr(dm_resp.random, "uniform", lambda a, b: 60.0)
    assert responder._next_poll_delay() == 180.0
    monkeypatch.setattr(dm_resp.random, "uniform", lambda a, b: 30.0)
    assert responder._next_poll_delay() == 150.0


def test_next_poll_delay_always_inside_range():
    responder = DMResponder(seen_path="/tmp/nope.json")
    for _ in range(50):
        delay = responder._next_poll_delay()
        assert 120.0 <= delay <= 180.0


# --------------------------------------------------------------------
# Warning classifier
# --------------------------------------------------------------------


def test_warning_classifier_matches_instagram_blocks():
    assert _is_instagram_warning(ChallengeRequired("challenge_required")) is True
    assert _is_instagram_warning(FeedbackRequired("feedback_required")) is True
    assert _is_instagram_warning(Exception("LoginRequired: login_required")) is True
    assert _is_instagram_warning(Exception("PleaseWaitFewMinutes")) is True
    assert _is_instagram_warning(Exception("SentryBlock: blocked")) is True
    assert _is_instagram_warning(Exception("rate limit exceeded")) is True


def test_warning_classifier_ignores_plain_errors():
    assert _is_instagram_warning(Exception("connection reset by peer")) is False
    assert _is_instagram_warning(Exception("timed out")) is False
    assert _is_instagram_warning(None) is False


# --------------------------------------------------------------------
# Reply pacing (pure math) + hourly cap
# --------------------------------------------------------------------


def test_reply_wait_is_longer_of_global_and_thread_gap(tmp_path, real_gaps):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    assert responder._reply_wait_seconds("instagram", "instagram:t1") == 0.0
    responder._last_send_at = {"global": 1000.0, "instagram:t1": 1000.0}
    # 10s after a send: global gap wants 10 more, thread gap 50 more.
    assert responder._reply_wait_seconds("instagram", "instagram:t1", now=1010.0) == 50.0
    # 50s after: global gap met, thread gap wants 10 more.
    assert responder._reply_wait_seconds("instagram", "instagram:t1", now=1050.0) == 10.0
    # A different thread only owes the global gap.
    assert responder._reply_wait_seconds("instagram", "instagram:t2", now=1010.0) == 10.0
    # Past both gaps: no wait.
    assert responder._reply_wait_seconds("instagram", "instagram:t1", now=1070.0) == 0.0


def test_hourly_cap_counts_and_prunes(tmp_path, real_gaps):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    now = time.monotonic()
    responder._send_times["instagram"] = [now - 100.0] * 19
    assert responder._auto_replies_this_hour("instagram", now=now) == 19
    responder._send_times["instagram"].append(now - 10.0)
    assert responder._auto_replies_this_hour("instagram", now=now) == 20
    # Entries older than an hour do not count.
    responder._send_times["instagram"] = [now - 3700.0] * 25
    assert responder._auto_replies_this_hour("instagram", now=now) == 0


@pytest.mark.asyncio
async def test_check_pace_refuses_at_cap(tmp_path, real_gaps):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    now = time.monotonic()
    responder._send_times["instagram"] = [now - 60.0] * 20
    assert await responder._check_pace("instagram", "instagram:t1") is False
    responder._send_times["instagram"] = [now - 60.0] * 19
    assert await responder._check_pace("instagram", "instagram:t1") is True


@pytest.mark.asyncio
async def test_paced_send_records_and_caps(tmp_path, monkeypatch):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    fake = _FakeIGClient()
    assert await responder._paced_send(fake, "instagram", "t1", "hi") is True
    assert await responder._paced_send(fake, "instagram", "t2", "hi") is True
    assert len(fake.sent) == 2
    assert len(responder._send_times["instagram"]) == 2
    # Cap hit: no send, no exception — the caller retries later.
    monkeypatch.setattr(dm_resp, "_MAX_AUTO_REPLIES_PER_HOUR", 2)
    assert await responder._paced_send(fake, "instagram", "t3", "hi") is False
    assert len(fake.sent) == 2


# --------------------------------------------------------------------
# Session reuse: one client, validate only when fresh
# --------------------------------------------------------------------


def test_cached_client_reused_until_credentials_change(tmp_path):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    builds = []

    def build(platform, method, data):
        client = SimpleNamespace()
        builds.append(client)
        return client

    responder._build_client = build
    data_a = {"cookies": {"sessionid": "aaa"}}
    data_b = {"cookies": {"sessionid": "bbb"}}
    first, fresh_first = responder._get_cached_client("instagram", "cookies", data_a)
    assert fresh_first is True
    second, fresh_second = responder._get_cached_client("instagram", "cookies", data_a)
    assert second is first
    assert fresh_second is False
    assert len(builds) == 1
    third, fresh_third = responder._get_cached_client("instagram", "cookies", data_b)
    assert third is not first
    assert fresh_third is True
    assert len(builds) == 2


@pytest.mark.asyncio
async def test_validate_runs_once_per_client_lifetime(
    tmp_path, monkeypatch, tmp_warning_store
):
    """First poll validates the fresh client; later polls skip the
    extra account_info() call and trust list_recent."""
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    fake = _FakeIGClient(messages=[])
    _wire_instagram(monkeypatch, responder, fake)
    await responder.poll_once()
    await responder.poll_once()
    await responder.poll_once()
    assert fake.validate_calls == 1
    assert fake.list_calls == 3


@pytest.mark.asyncio
async def test_session_error_drops_cached_client(
    tmp_path, monkeypatch, tmp_warning_store
):
    """A plain (non-warning) list failure drops the client, so the
    next poll rebuilds and re-validates — without locking out."""
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    fake = _FakeIGClient(messages=[])
    _wire_instagram(monkeypatch, responder, fake)
    await responder.poll_once()
    assert fake.validate_calls == 1
    fake._list_error = Exception("connection reset by peer")
    result = await responder.poll_once()
    assert result["instagram"]["ok"] is False
    assert responder._is_instagram_locked_out() is False
    fake._list_error = None
    await responder.poll_once()
    assert fake.validate_calls == 2  # rebuilt + re-validated
    assert fake.list_calls == 3


# --------------------------------------------------------------------
# Instagram warning lockout
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_challenge_locks_out_and_alerts_once(
    tmp_path, monkeypatch, tmp_warning_store
):
    """A challenge on list_recent: polling stops, Sir gets ONE
    Telegram alert, and later polls skip Instagram without alerting
    again."""
    telegrams = []

    async def fake_telegram(text, client=None):
        telegrams.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    fake = _FakeIGClient(
        messages=[], list_error=ChallengeRequired("challenge_required")
    )
    _wire_instagram(monkeypatch, responder, fake)
    result = await responder.poll_once()
    assert result["instagram"]["ok"] is False
    assert responder._is_instagram_locked_out() is True
    assert len(telegrams) == 1
    assert "STOPPED" in telegrams[0]
    assert "Reconnect Instagram" in telegrams[0]
    # The lockout survives a fresh responder instance (durable store).
    second = DMResponder(seen_path=str(tmp_path / "seen2.json"))
    assert second._is_instagram_locked_out() is True
    # Later polls skip Instagram entirely — no more alerts, no retries.
    result2 = await responder.poll_once()
    assert result2["instagram"]["skipped"] is True
    assert result2["instagram"]["reason"] == "instagram_warning_lockout"
    assert len(telegrams) == 1
    assert fake.list_calls == 1  # never polled again


@pytest.mark.asyncio
async def test_lockout_clears_when_sir_reconnects(
    tmp_path, monkeypatch, tmp_warning_store
):
    """New credentials (a reconnect) clear the lockout; polling resumes."""
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        AsyncMock(return_value=True),
    )
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    fake = _FakeIGClient(
        messages=[], list_error=ChallengeRequired("challenge_required")
    )
    blob_a = {"method": "cookies", "data": {"cookies": {"sessionid": "aaa"}}}
    _wire_instagram(monkeypatch, responder, fake, blob=blob_a)
    await responder.poll_once()
    assert responder._is_instagram_locked_out() is True
    # Same credentials: still locked out.
    await responder.poll_once()
    assert responder._is_instagram_locked_out() is True
    # Sir reconnects with fresh credentials: the flag clears and the
    # poll goes through (the challenge is gone now).
    fake._list_error = None
    blob_b = {"method": "cookies", "data": {"cookies": {"sessionid": "bbb"}}}
    _wire_instagram(monkeypatch, responder, fake, blob=blob_b)
    result = await responder.poll_once()
    assert responder._is_instagram_locked_out() is False
    assert result["instagram"]["ok"] is True


@pytest.mark.asyncio
async def test_validate_false_with_warning_locks_out(
    tmp_path, monkeypatch, tmp_warning_store
):
    """A fresh client whose session check fails with a warning error
    locks out instead of retrying the login every poll."""
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        AsyncMock(return_value=True),
    )
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))

    class _BadSessionClient(_FakeIGClient):
        def validate(self):
            self.validate_calls += 1
            self.last_error = "LoginRequired: login_required"
            return False

    fake = _BadSessionClient(messages=[])
    _wire_instagram(monkeypatch, responder, fake)
    result = await responder.poll_once()
    assert result["instagram"]["ok"] is False
    assert "expired" in result["instagram"]["error"]
    assert responder._is_instagram_locked_out() is True


def test_status_reports_lockout(tmp_path, monkeypatch, tmp_warning_store):
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    monkeypatch.setattr(
        dm_resp.dm_auth, "connector_status",
        lambda p: {"connected": p == "instagram"},
    )
    status = responder.get_status()
    assert status["platforms"]["instagram"]["warning_lockout"] is False
    dm_store.instagram_warning.set("lockout", {
        "active": True, "reason": "test", "since": "2026-11-12T00:00:00+00:00",
        "fingerprint": "abc",
    })
    assert responder._is_instagram_locked_out() is True
    status = responder.get_status()
    assert status["platforms"]["instagram"]["warning_lockout"] is True
    assert status["platforms"]["messenger"]["warning_lockout"] is False
