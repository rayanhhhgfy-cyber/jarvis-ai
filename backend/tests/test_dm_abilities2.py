# ====================================================================
# JARVIS OMEGA — DM Abilities Wave 2 Tests
# ====================================================================
"""
Tests for voice replies, scheduled messages, reminders, smart away
status, spam filter, calendar, contact memory, birthdays, quiet hours
and DM search. All external calls are mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from backend.services.dm_responder import (
    DMResponder,
    _in_quiet_hours,
    _is_abusive,
    _is_availability_question,
    _is_away_question,
)
from backend.services.dm_time import describe_time, parse_time

_AMMAN = ZoneInfo("Asia/Amman")


# --------------------------------------------------------------------
# Time parsing
# --------------------------------------------------------------------

def test_parse_time_in_hours():
    now = datetime(2026, 11, 10, 10, 0, tzinfo=_AMMAN)
    result = parse_time("in 2 hours", now=now)
    assert result == datetime(2026, 11, 10, 12, 0, tzinfo=_AMMAN)


def test_parse_time_tomorrow_at_5pm():
    now = datetime(2026, 11, 10, 10, 0, tzinfo=_AMMAN)
    result = parse_time("tomorrow at 5pm", now=now)
    assert result == datetime(2026, 11, 11, 17, 0, tzinfo=_AMMAN)


def test_parse_time_at_5pm_rolls_to_tomorrow_when_past():
    now = datetime(2026, 11, 10, 18, 0, tzinfo=_AMMAN)
    result = parse_time("at 5pm", now=now)
    assert result == datetime(2026, 11, 11, 17, 0, tzinfo=_AMMAN)


def test_parse_time_friday():
    # 2026-11-10 is a Tuesday; Friday is 2026-11-13.
    now = datetime(2026, 11, 10, 10, 0, tzinfo=_AMMAN)
    result = parse_time("Friday", now=now)
    assert result is not None
    assert result.date() == datetime(2026, 11, 13).date()
    assert result.hour == 18


def test_parse_time_unknown_is_none():
    assert parse_time("some time later") is None
    assert parse_time("") is None


def test_describe_time():
    now = datetime.now(_AMMAN)
    assert "today" in describe_time(now)
    assert "tomorrow" in describe_time(now + timedelta(days=1))


# --------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------

def test_is_away_question():
    assert _is_away_question("when will he be back?") is True
    assert _is_away_question("متى بيرجع ريان؟") is True
    assert _is_away_question("hi, how are you?") is False


def test_is_availability_question():
    assert _is_availability_question("are you free Friday?") is True
    assert _is_availability_question("is Rayyan free tomorrow?") is True
    assert _is_availability_question("what is the weather?") is False


def test_is_abusive():
    assert _is_abusive("you are stupid") is True
    assert _is_abusive("hello friend") is False


def test_in_quiet_hours(monkeypatch):
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_quiet_hours_start", "23:00")
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_quiet_hours_end", "07:00")
    late = datetime(2026, 11, 10, 2, 0, tzinfo=_AMMAN)
    assert _in_quiet_hours(late) is True
    noon = datetime(2026, 11, 10, 12, 0, tzinfo=_AMMAN)
    assert _in_quiet_hours(noon) is False


# --------------------------------------------------------------------
# Voice: pick the right voice; failure falls back to text
# --------------------------------------------------------------------

def test_pick_voice():
    from backend.services.dm_voice import _pick_voice

    assert "ar-SA" in _pick_voice("مرحبا كيف حالك")
    assert "en-US" in _pick_voice("Hello, how are you?")


@pytest.mark.asyncio
async def test_send_voice_reply_tts_failure_returns_false(monkeypatch):
    """When TTS fails, the voice reply returns False (caller sends text)."""
    from backend.services.dm_voice import send_voice_reply

    monkeypatch.setattr(
        "backend.services.dm_voice._synthesize_mp3",
        AsyncMock(return_value=None),
    )
    assert await send_voice_reply(MagicMock(), "t1", "hello") is False


# --------------------------------------------------------------------
# Scheduled messages + reminders (responder + stores)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_due_scheduled(tmp_path, monkeypatch):
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.scheduled_dms, "_path", tmp_path / "scheduled_dms.json")
    monkeypatch.setattr(dm_store.scheduled_dms, "_loaded", False)
    monkeypatch.setattr(dm_store.scheduled_dms, "_data", {})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    past = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=5)
    responder.schedule_dm("Omar", "I will be there at 5.", past)
    future = datetime.now(ZoneInfo("UTC")) + timedelta(hours=2)
    responder.schedule_dm("Layla", "Hello!", future)

    sent = []
    async def fake_send(name, text):
        sent.append((name, text))
        return {"ok": True, "sender_name": name}

    monkeypatch.setattr(responder, "send_dm_to_name", fake_send)
    assert await responder.run_due_scheduled() == 1
    assert sent == [("Omar", "I will be there at 5.")]
    # The future one is still queued.
    assert len(dm_store.scheduled_dms.all()) == 1


@pytest.mark.asyncio
async def test_run_due_reminders(tmp_path, monkeypatch):
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.reminders, "_path", tmp_path / "reminders.json")
    monkeypatch.setattr(dm_store.reminders, "_loaded", False)
    monkeypatch.setattr(dm_store.reminders, "_data", {})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    past = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=5)
    responder.add_reminder("reply to Omar", past)

    sent = []
    async def fake_telegram(text, client=None):
        sent.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    assert await responder.run_due_reminders() == 1
    assert len(sent) == 1
    assert "reply to Omar" in sent[0]


# --------------------------------------------------------------------
# Birthdays
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_birthdays(tmp_path, monkeypatch):
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    today = datetime.now(ZoneInfo("UTC")).date()
    dm_store.contacts.set("Omar", {"birthday": f"{today.month:02d}-{today.day:02d}"})
    dm_store.contacts.set("Layla", {"birthday": "01-01"})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))

    sent = []
    async def fake_telegram(text, client=None):
        sent.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    assert await responder.check_birthdays() == 1
    assert "Omar" in sent[0]
    assert "birthday" in sent[0].lower()


# --------------------------------------------------------------------
# DM search (activity feed)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_dms_activity(tmp_path):
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    responder._record_activity(
        "instagram", {"sender_name": "Omar", "text": "the book is great"}, "Glad!", False,
    )
    responder._record_activity(
        "instagram", {"sender_name": "Layla", "text": "hello"}, "Hi!", False,
    )
    results = await responder.search_dms("book")
    assert len(results) == 1
    assert results[0]["sender_name"] == "Omar"
    assert await responder.search_dms("nothing here") == []


# --------------------------------------------------------------------
# Remember + busy/free helpers (Telegram intents)
# --------------------------------------------------------------------

def test_handle_remember_fact(tmp_path, monkeypatch):
    from backend.routers.router_telegram import _handle_remember
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    reply = _handle_remember("Omar loves football")
    assert "Omar" in reply
    assert "football" in dm_store.contacts.get("Omar", {}).get("notes", "")


def test_handle_remember_birthday(tmp_path, monkeypatch):
    from backend.routers.router_telegram import _handle_remember
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    reply = _handle_remember("Omar's birthday is March 15")
    assert "March 15" in reply
    assert dm_store.contacts.get("Omar", {}).get("birthday") == "03-15"


def test_handle_busy_free(tmp_path, monkeypatch):
    from backend.routers.router_telegram import _handle_busy_free
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    reply = _handle_busy_free("busy", "Friday 5pm-8pm")
    assert "busy" in reply.lower()
    assert "Friday" in reply
    assert len(dm_store.calendar.all()) == 1


# --------------------------------------------------------------------
# Wave 3: rules, meetings, tone
# --------------------------------------------------------------------

def test_match_rule(tmp_path, monkeypatch):
    from backend.services import dm_store
    from backend.services.dm_responder import _match_rule

    monkeypatch.setattr(dm_store.rules, "_path", tmp_path / "dm_rules.json")
    monkeypatch.setattr(dm_store.rules, "_loaded", False)
    monkeypatch.setattr(dm_store.rules, "_data", {})
    dm_store.rules.set("r1", {
        "person": "Omar", "topic": "club",
        "reply": "Here is the club link: https://f-thinkers.vercel.app",
    })
    dm_store.rules.set("r2", {
        "person": "anyone", "topic": "price",
        "reply": "Check my portfolio for prices.",
    })
    assert _match_rule("Omar", "tell me about the club") == (
        "Here is the club link: https://f-thinkers.vercel.app"
    )
    assert _match_rule("Layla", "what is the price?") == "Check my portfolio for prices."
    assert _match_rule("Layla", "tell me about the club") is None
    assert _match_rule("Omar", "hello") is None


def test_is_meeting_request():
    from backend.services.dm_responder import _is_meeting_request

    assert _is_meeting_request("can we meet tomorrow?") is True
    assert _is_meeting_request("let's meet up") is True
    assert _is_meeting_request("how are you?") is False


def test_contact_tone(tmp_path, monkeypatch):
    from backend.services import dm_store
    from backend.services.dm_responder import _contact_tone

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    dm_store.contacts.set("Omar", {"tone": "casual"})
    dm_store.contacts.set("Mr. Ahmad", {"tone": "formal"})
    assert _contact_tone("Omar") == "casual"
    assert _contact_tone("Mr. Ahmad") == "formal"
    # A formal title defaults to formal even without a stored tone.
    assert _contact_tone("Dr. Sara") == "formal"
    assert _contact_tone("Layla") is None


def test_handle_remember_tone(tmp_path, monkeypatch):
    from backend.routers.router_telegram import _handle_remember
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    reply = _handle_remember("Mr. Ahmad is a teacher")
    assert "formally" in reply
    assert dm_store.contacts.get("Mr. Ahmad", {}).get("tone") == "formal"
    reply = _handle_remember("Omar is a friend")
    assert "casually" in reply
    assert dm_store.contacts.get("Omar", {}).get("tone") == "casual"


def test_format_offered_times():
    from backend.routers.router_telegram import _format_offered_times

    one = _format_offered_times(["2026-11-13T17:00:00+03:00"])
    assert "Friday" in one and "17:00" in one
    two = _format_offered_times([
        "2026-11-13T17:00:00+03:00", "2026-11-14T10:00:00+03:00",
    ])
    assert "or" in two
    assert "Friday" in two and "Saturday" in two
