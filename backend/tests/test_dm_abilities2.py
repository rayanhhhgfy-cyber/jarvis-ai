# ====================================================================
# JARVIS OMEGA — DM Abilities Wave 2 Tests
# ====================================================================
"""
Tests for voice replies, scheduled messages, reminders, smart away
status, spam filter, calendar, contact memory, birthdays, quiet hours
and DM search. All external calls are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


# --------------------------------------------------------------------
# Wave 4: birthday wishes + group welcome
# --------------------------------------------------------------------

def test_birthday_wish_text_default():
    from backend.services.dm_responder import DMResponder

    text = DMResponder._birthday_wish_text("Omar")
    assert "Omar" in text
    assert "Happy birthday" in text


def test_birthday_wish_text_custom(tmp_path, monkeypatch):
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.settings, "_path", tmp_path / "dm_settings.json")
    monkeypatch.setattr(dm_store.settings, "_loaded", False)
    monkeypatch.setattr(dm_store.settings, "_data", {})
    dm_store.settings.set("birthday_message", "Happy birthday {name}, have a great one!")
    assert DMResponder._birthday_wish_text("Omar") == "Happy birthday Omar, have a great one!"


@pytest.mark.asyncio
async def test_check_birthdays_sends_wish_today(tmp_path, monkeypatch):
    """On the birthday itself Jarvis sends the wish in the DM + tells Sir."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    today = datetime.now(UTC).date()
    dm_store.contacts.set("Omar", {"birthday": today.strftime("%m-%d")})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent_wishes = []

    async def fake_send_dm(name, text):
        sent_wishes.append((name, text))
        return {"ok": True, "platform": "instagram", "sender_name": name}

    monkeypatch.setattr(responder, "send_dm_to_name", fake_send_dm)
    sent_telegram = []

    async def fake_telegram(text, client=None):
        sent_telegram.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    sent = await responder.check_birthdays()
    assert sent == 1
    assert len(sent_wishes) == 1
    assert sent_wishes[0][0] == "Omar"
    assert "Happy birthday" in sent_wishes[0][1]
    assert "sent them a birthday wish" in sent_telegram[0]


@pytest.mark.asyncio
async def test_check_birthdays_tomorrow_no_wish(tmp_path, monkeypatch):
    """A birthday tomorrow gets only the note — no wish sent yet."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    dm_store.contacts.set("Omar", {"birthday": tomorrow.strftime("%m-%d")})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))

    async def fake_send_dm(name, text):
        raise AssertionError("no wish should be sent for tomorrow")

    monkeypatch.setattr(responder, "send_dm_to_name", fake_send_dm)
    sent_telegram = []

    async def fake_telegram(text, client=None):
        sent_telegram.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    sent = await responder.check_birthdays()
    assert sent == 1
    assert "tomorrow" in sent_telegram[0]


@pytest.mark.asyncio
async def test_group_welcome_newcomer(tmp_path, monkeypatch):
    """A newcomer to a known group gets one welcome; the first sight of
    a group only learns its members."""
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))

    class _FakeClient:
        def __init__(self):
            self.sent = []

        async def send(self, thread_id, text):
            self.sent.append((thread_id, text))
            return {"ok": True}

    fake = _FakeClient()
    # First sight: learns the members, says nothing.
    await responder._welcome_newcomers(
        "instagram", fake,
        {"thread_id": "g1", "members": ["Omar", "Layla"]},
    )
    assert fake.sent == []
    # A new member appears: welcomed once.
    await responder._welcome_newcomers(
        "instagram", fake,
        {"thread_id": "g1", "members": ["Omar", "Layla", "Sara"]},
    )
    assert len(fake.sent) == 1
    assert "Sara" in fake.sent[0][1]
    assert "Welcome" in fake.sent[0][1]
    # Same members again: no repeat.
    await responder._welcome_newcomers(
        "instagram", fake,
        {"thread_id": "g1", "members": ["Omar", "Layla", "Sara"]},
    )
    assert len(fake.sent) == 1


@pytest.mark.asyncio
async def test_group_welcome_custom_message(tmp_path, monkeypatch):
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.settings, "_path", tmp_path / "dm_settings.json")
    monkeypatch.setattr(dm_store.settings, "_loaded", False)
    monkeypatch.setattr(dm_store.settings, "_data", {})
    dm_store.settings.set("group_welcome_message", "Hey {name}, welcome in!")
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    responder._group_members["g1"] = {"Omar"}

    class _FakeClient:
        def __init__(self):
            self.sent = []

        async def send(self, thread_id, text):
            self.sent.append((thread_id, text))
            return {"ok": True}

    fake = _FakeClient()
    await responder._welcome_newcomers(
        "instagram", fake,
        {"thread_id": "g1", "members": ["Omar", "Sara"]},
    )
    assert fake.sent[0][1] == "Hey Sara, welcome in!"


# --------------------------------------------------------------------
# Wave 5: busy with reason + missed calls
# --------------------------------------------------------------------

def test_parse_time_window():
    from backend.services.dm_time import parse_time_window

    now = datetime(2026, 11, 13, 12, 0, tzinfo=ZoneInfo("Asia/Amman"))  # Friday
    start, end = parse_time_window("Friday 5pm-8pm", now)
    assert start.hour == 17 and start.minute == 0
    assert end.hour == 20 and end.minute == 0
    assert start.date().isoformat() == "2026-11-13"
    start, end = parse_time_window("from 5pm to 8pm", now)
    assert start.hour == 17 and end.hour == 20
    start, end = parse_time_window("Saturday", now)
    assert start is not None and end is None


def test_handle_busy_free_with_reason(tmp_path, monkeypatch):
    from backend.routers.router_telegram import _handle_busy_free
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    reply = _handle_busy_free(
        "busy", "Friday 5pm-8pm because I have football practice"
    )
    assert "Friday" in reply
    assert "17:00" in reply and "20:00" in reply
    assert "football practice" in reply
    entries = dm_store.calendar.all()
    assert len(entries) == 1
    entry = next(iter(entries.values()))
    assert entry["status"] == "busy"
    assert entry["detail"] == "I have football practice"
    assert entry["from"] is not None and entry["to"] is not None


def test_busy_now_and_text(tmp_path, monkeypatch):
    """A busy window covering right now is found; outside it, nothing."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    now = datetime.now(UTC)
    dm_store.calendar.set(now.date().isoformat(), {
        "date": now.date().isoformat(),
        "status": "busy",
        "detail": "football practice",
        "from": (now - timedelta(hours=1)).isoformat(),
        "to": (now + timedelta(hours=1)).isoformat(),
    })
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    entry = responder._busy_now()
    assert entry is not None
    assert responder._busy_text(entry) == "busy until " + (
        now + timedelta(hours=1)
    ).strftime("%H:%M") + " — football practice"
    # A window that already ended is not busy now.
    dm_store.calendar.set(now.date().isoformat(), {
        "date": now.date().isoformat(),
        "status": "busy",
        "detail": "football practice",
        "from": (now - timedelta(hours=3)).isoformat(),
        "to": (now - timedelta(hours=1)).isoformat(),
    })
    assert responder._busy_now() is None


def test_calendar_answer_with_reason(tmp_path, monkeypatch):
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    dm_store.calendar.set("2026-11-13", {
        "date": "2026-11-13",
        "status": "busy",
        "detail": "football practice",
        "from": "2026-11-13T17:00:00+03:00",
        "to": "2026-11-13T20:00:00+03:00",
    })
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    answer = responder._calendar_answer("are you free Friday?")
    assert answer is not None
    assert "busy" in answer
    assert "17:00" in answer and "20:00" in answer
    assert "football practice" in answer


def test_instagram_call_detection():
    from backend.services.dm_clients import _instagram_call

    class _Msg:
        def __init__(self, item_type, is_sent_by_viewer):
            self.item_type = item_type
            self.is_sent_by_viewer = is_sent_by_viewer

    assert _instagram_call(_Msg("video_call", False)) is True
    assert _instagram_call(_Msg("voice_call", False)) is True
    # Sir made the call himself — not missed.
    assert _instagram_call(_Msg("video_call", True)) is False
    assert _instagram_call(_Msg("text", False)) is False



def test_parse_time_bare_clock_next_occurrence():
    """A bare clock ('4:05') means the NEXT occurrence of that time —
    this afternoon when it is 4:04 PM, not 4:05 AM tomorrow."""
    now = datetime(2026, 11, 10, 16, 4, tzinfo=_AMMAN)
    assert parse_time("4:05", now=now) == datetime(2026, 11, 10, 16, 5, tzinfo=_AMMAN)
    assert parse_time("at 4:05", now=now) == datetime(2026, 11, 10, 16, 5, tzinfo=_AMMAN)
    assert parse_time("4:05pm", now=now) == datetime(2026, 11, 10, 16, 5, tzinfo=_AMMAN)
    # In the morning, the same clock is this morning.
    morning = datetime(2026, 11, 10, 3, 0, tzinfo=_AMMAN)
    assert parse_time("4:05", now=morning) == datetime(2026, 11, 10, 4, 5, tzinfo=_AMMAN)
    # Once both have passed, it rolls to tomorrow morning.
    evening = datetime(2026, 11, 10, 17, 0, tzinfo=_AMMAN)
    assert parse_time("4:05", now=evening) == datetime(2026, 11, 11, 4, 5, tzinfo=_AMMAN)
    # A 24-hour clock still works.
    assert parse_time("17:00", now=now) == datetime(2026, 11, 10, 17, 0, tzinfo=_AMMAN)


def test_parse_time_bare_number_is_not_a_clock():
    """A bare number ('call Omar 5 times') is not a time."""
    now = datetime(2026, 11, 10, 10, 0, tzinfo=_AMMAN)
    assert parse_time("call Omar 5 times", now=now) is None


# --------------------------------------------------------------------
# Outbound call: Jarvis calls Sir when something is important
# --------------------------------------------------------------------

def _reset_call_store(monkeypatch, tmp_path):
    from backend.services import dm_store

    monkeypatch.setattr(dm_store.call_request, "_path", tmp_path / "call_request.json")
    monkeypatch.setattr(dm_store.call_request, "_loaded", False)
    monkeypatch.setattr(dm_store.call_request, "_data", {})


@pytest.mark.asyncio
async def test_initiate_call_stores_reason_and_rings(monkeypatch, tmp_path):
    """initiate_call stores the reason and sends the Telegram ring."""
    from backend.services.dm_responder import initiate_call

    _reset_call_store(monkeypatch, tmp_path)
    sent: list[str] = []

    async def fake_telegram(text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    ok = await initiate_call("Instagram — Omar wrote: urgent, call me")
    assert ok is True
    assert len(sent) == 1
    assert "Jarvis is calling" in sent[0]
    assert "https://jarvis-call-smoky.vercel.app" in sent[0]
    assert "Omar" in sent[0]


@pytest.mark.asyncio
async def test_take_pending_call_reason_once(monkeypatch, tmp_path):
    """A pending call reason is consumed exactly once."""
    from backend.services.dm_responder import (
        initiate_call,
        take_pending_call_reason,
    )

    _reset_call_store(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        AsyncMock(return_value=True),
    )
    await initiate_call("Something important came up.")
    assert take_pending_call_reason() == "Something important came up."
    assert take_pending_call_reason() is None


@pytest.mark.asyncio
async def test_take_pending_call_reason_expires(monkeypatch, tmp_path):
    """A stale call reason is dropped, never spoken."""
    import time

    from backend.services import dm_store
    from backend.services.dm_responder import take_pending_call_reason

    _reset_call_store(monkeypatch, tmp_path)
    dm_store.call_request.set(
        "pending", {"reason": "Old news.", "created_at": time.time() - 3600}
    )
    assert take_pending_call_reason(max_age_seconds=900) is None


@pytest.mark.asyncio
async def test_initiate_call_also_sends_web_push(monkeypatch, tmp_path):
    """initiate_call rings Sir with a web push as well as Telegram."""
    from backend.services.dm_responder import initiate_call

    _reset_call_store(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        AsyncMock(return_value=True),
    )
    sent: list[object] = []

    async def fake_push(notification):
        sent.append(notification)
        return True

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        fake_push,
    )
    ok = await initiate_call("Instagram — Omar wrote: urgent, call me")
    assert ok is True
    assert len(sent) == 1
    push = sent[0]
    assert "calling" in push.title.lower()
    assert "Omar" in push.body
    assert push.category == "call"
    assert push.action_url == "https://jarvis-call-smoky.vercel.app/?answer=1"
