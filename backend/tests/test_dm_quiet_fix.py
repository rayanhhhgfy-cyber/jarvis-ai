# ====================================================================
# JARVIS OMEGA — quiet-DM fix tests
# ====================================================================
"""
Tests for the 2026-11-11 DM fix (Rayyan's screenshots): one alert per
DM with a 30-minute call cooldown, echo-loop detection, follow-up
replies that remember what Jarvis already said, Jordanian-dialect
understanding, the sender's @username instead of "Unknown", durable
mutes that expire, and voice-note DMs that always get a reply.

ALL data here is fake. No real login is attempted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services import dm_store
from backend.services.dm_clients import (
    _instagram_sender_name,
    _instagram_username,
)
from backend.services.dm_llm import _messages, generate_dm_reply
from backend.services.dm_responder import (
    DMResponder,
    _display_sender,
    _is_echo,
)

# --------------------------------------------------------------------
# Echo detection
# --------------------------------------------------------------------


def test_echo_exact_match():
    reply = "وعليكم السلام، أنا جارفيس مساعد ريان. هو مشغول الآن."
    assert _is_echo(reply, reply) is True


def test_echo_case_and_punctuation_insensitive():
    reply = "Thanks! If it's urgent, just let me know."
    assert _is_echo("thanks if its urgent just let me know", reply) is True


def test_echo_contained_either_way():
    reply = "Sure thing, I'll make sure Rayyan sees this. Let me know if there's anything urgent."
    assert _is_echo("Sure thing, I'll make sure Rayyan sees this.", reply) is True
    assert _is_echo(reply + " Thank you so much!", reply) is True


def test_echo_short_text_never_counts():
    assert _is_echo("ok", "ok") is False
    assert _is_echo("yes please", "yes please") is False


def test_echo_different_message_is_not_echo():
    reply = "وعليكم السلام، أنا جارفيس مساعد ريان. هو مشغول الآن."
    assert _is_echo("ضروري يفتح الواتس الان", reply) is False
    assert _is_echo("hello", None) is False


# --------------------------------------------------------------------
# Sender display: username, never bare "Unknown"
# --------------------------------------------------------------------


def test_display_sender_prefers_name():
    assert _display_sender({"sender_name": "محمد الجمل"}) == "محمد الجمل"


def test_display_sender_falls_back_to_username():
    msg = {"sender_name": "Unknown", "sender_username": "mohammed.aljamal"}
    assert _display_sender(msg) == "@mohammed.aljamal"


def test_display_sender_unknown_without_username():
    assert _display_sender({"sender_name": "Unknown"}) == "Unknown"


def test_instagram_sender_name_from_thread_participant():
    """The message's user object is empty — the thread's other
    participant carries the name (this is the dad's case)."""
    last = SimpleNamespace(user=SimpleNamespace(full_name="", username=""))
    users = [SimpleNamespace(pk="777", full_name="محمد الجمل", username="mohammed.aljamal")]
    assert _instagram_sender_name(last, users, self_id="111") == "محمد الجمل"
    assert _instagram_username(last, users, self_id="111") == "mohammed.aljamal"


def test_instagram_sender_name_prefers_message_user():
    last = SimpleNamespace(
        user=SimpleNamespace(full_name="Sara", username="sara_lee")
    )
    users = [SimpleNamespace(pk="888", full_name="Other", username="other")]
    assert _instagram_sender_name(last, users, self_id="111") == "Sara"
    assert _instagram_username(last, users, self_id="111") == "sara_lee"


def test_instagram_sender_name_skips_self():
    last = SimpleNamespace(user=SimpleNamespace(full_name="", username=""))
    users = [
        SimpleNamespace(pk="111", full_name="Rayyan", username="rayyan"),
        SimpleNamespace(pk="777", full_name="", username="dad_handle"),
    ]
    assert _instagram_username(last, users, self_id="111") == "dad_handle"


# --------------------------------------------------------------------
# Follow-up prompt remembers the last reply
# --------------------------------------------------------------------


def test_follow_up_prompt_includes_last_reply():
    last = "وعليكم السلام، أنا جارفيس مساعد ريان. هو مشغول الآن."
    messages = _messages("Omar", "ضروري يفتح الواتس الان", first_reply=False, last_reply=last)
    system = messages[0]["content"]
    assert last in system
    assert "Do not repeat it" in system


def test_first_reply_prompt_has_no_last_reply_block():
    messages = _messages("Omar", "hello", first_reply=True, last_reply="anything")
    assert "Your last reply" not in messages[0]["content"]


def test_follow_up_prompt_understands_dialect():
    messages = _messages("Omar", "هسا جاوبني ضروري", first_reply=False)
    system = messages[0]["content"]
    assert "هسا" in system
    assert "WhatsApp" in system


# --------------------------------------------------------------------
# Voice notes: transcript flows through, failure still gets a reply
# --------------------------------------------------------------------


def _groq_client(captured):
    """Mock Groq transport that records the payload and answers once."""

    def handler(request):
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "تمام، رح أخبر ريان."}}],
        })

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_voice_note_transcript_becomes_the_message(monkeypatch):
    """A voice note is transcribed and the transcript is what the LLM
    answers — and it is returned so Sir's alert shows what was said."""
    monkeypatch.setattr(
        "backend.services.dm_media.transcribe_audio",
        AsyncMock(return_value="ضروري يفتح الواتس الان"),
    )
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr(
        "backend.services.model_settings.get_active_model",
        lambda: "groq-120b",
    )
    captured = []
    gen = await generate_dm_reply(
        "instagram", "محمد الجمل", "",
        client=_groq_client(captured),
        first_reply=False,
        media_url="https://example.invalid/voice.mp4",
        media_type="voice",
    )
    assert gen["ok"] is True
    assert gen["transcript"] == "ضروري يفتح الواتس الان"
    assert gen["voice_failed"] is False
    # The LLM saw the transcript, not an empty message.
    assert "ضروري يفتح الواتس الان" in captured[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_voice_note_transcribe_failure_still_replies(monkeypatch):
    """When Whisper hears nothing, the sender still gets an honest
    reply instead of the generic intro — and the failure is flagged."""
    monkeypatch.setattr(
        "backend.services.dm_media.transcribe_audio",
        AsyncMock(return_value=None),
    )
    gen = await generate_dm_reply(
        "instagram", "محمد الجمل", "",
        client=_groq_client([]),
        first_reply=False,
        media_url="https://example.invalid/voice.mp4",
        media_type="voice",
    )
    assert gen["ok"] is True
    assert gen["voice_failed"] is True
    assert "couldn't hear" in gen["reply"]
    assert "الصوتية" in gen["reply"]


@pytest.mark.asyncio
async def test_last_reply_reaches_the_model(monkeypatch):
    """The follow-up prompt carries Jarvis's last reply to the LLM."""
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr(
        "backend.services.model_settings.get_active_model",
        lambda: "groq-120b",
    )
    captured = []
    last = "وعليكم السلام، أنا جارفيس مساعد ريان. هو مشغول الآن."
    gen = await generate_dm_reply(
        "instagram", "Omar", "ضروري يفتح الواتس الان",
        client=_groq_client(captured),
        first_reply=False,
        last_reply=last,
    )
    assert gen["ok"] is True
    assert last in captured[0]["messages"][0]["content"]


# --------------------------------------------------------------------
# One alert per DM + call cooldown
# --------------------------------------------------------------------


@pytest.fixture
def tmp_muted_store(tmp_path, monkeypatch):
    monkeypatch.setattr(dm_store.muted_threads, "_path", tmp_path / "muted_threads.json")
    monkeypatch.setattr(dm_store.muted_threads, "_loaded", False)
    monkeypatch.setattr(dm_store.muted_threads, "_data", {})
    return dm_store.muted_threads


@pytest.mark.asyncio
async def test_important_dm_alerts_once_and_rings_once(monkeypatch, tmp_path):
    """First important DM: ONE push (the call) + ONE Telegram message
    carrying the answer link. Second important DM in the same thread
    minutes later: ONE normal alert, no second ring."""
    pushes = []
    telegrams = []

    async def fake_push(notification):
        pushes.append(notification)
        return True

    async def fake_telegram(text, client=None):
        telegrams.append(text)
        return True

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        fake_push,
    )
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    msg = {
        "platform": "instagram",
        "thread_id": "t-dad",
        "sender_name": "Unknown",
        "sender_username": "mohammed.aljamal",
        "text": "ضروري يفتح الواتس الان",
        "message_id": "m1",
    }
    await responder._notify_new_dm("instagram", msg, important=True, reply="تمام.")
    await responder._notify_new_dm("instagram", msg, important=True, reply="تمام.")
    # Exactly one push + one Telegram per DM (2 each total).
    assert len(pushes) == 2
    assert len(telegrams) == 2
    # Only the first rang: call push + answer link.
    assert pushes[0].category == "call"
    assert pushes[1].category == "dm_reply"
    assert "Tap to answer" in telegrams[0]
    assert "Tap to answer" not in telegrams[1]
    # The sender is shown by handle, never "Unknown".
    assert "@mohammed.aljamal" in telegrams[0]
    assert "Unknown" not in telegrams[0]


@pytest.mark.asyncio
async def test_normal_dm_alerts_once(monkeypatch, tmp_path):
    pushes = []
    telegrams = []

    async def fake_push(notification):
        pushes.append(notification)
        return True

    async def fake_telegram(text, client=None):
        telegrams.append(text)
        return True

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        fake_push,
    )
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    msg = {
        "platform": "instagram",
        "thread_id": "t1",
        "sender_name": "Sara",
        "text": "hello",
        "message_id": "m1",
    }
    await responder._notify_new_dm("instagram", msg, important=False, reply="Hi!")
    assert len(pushes) == 1
    assert len(telegrams) == 1
    assert pushes[0].category == "dm_reply"
    assert "Tap to answer" not in telegrams[0]


# --------------------------------------------------------------------
# Durable mutes with expiry
# --------------------------------------------------------------------


def test_mute_survives_a_new_responder_instance(tmp_muted_store, tmp_path):
    """A mute is stored in dm_store: a fresh responder (a restart or
    redeploy) still sees it."""
    first = DMResponder(seen_path=str(tmp_path / "seen1.json"))
    first._mute_thread("instagram:t-dad", "محمد الجمل")
    second = DMResponder(seen_path=str(tmp_path / "seen2.json"))
    assert second._is_muted("instagram:t-dad") is True
    assert second.unmute_thread("محمد الجمل") is True
    assert second._is_muted("instagram:t-dad") is False
    assert second.unmute_thread("محمد الجمل") is False


def test_expired_mute_heals_itself(tmp_muted_store, tmp_path):
    """A mute older than an hour drops on sight — an automatic mute
    must never silence a real person forever."""
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    dm_store.muted_threads.set("instagram:t-dad", {
        "sender": "محمد الجمل", "muted_at": old,
    })
    assert responder._is_muted("instagram:t-dad") is False
    assert dm_store.muted_threads.get("instagram:t-dad") is None
