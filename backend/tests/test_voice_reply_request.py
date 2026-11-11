# ====================================================================
# JARVIS OMEGA — voice-reply request tests (2026-11-11)
# ====================================================================
"""
Sir's screenshot (2026-11-11 13:15): he asked "What do you know abt
yourself please answer with a voice note" and then "In a voice note",
and got the same TEXT reply twice. The bot only sent voice when HE
sent a voice note — a text request for a voice note was ignored.
_wants_voice_reply catches the request in free chat so the reply goes
out as voice.
"""

from __future__ import annotations

from backend.routers.router_telegram import _wants_voice_reply


def test_voice_reply_request_phrases():
    assert _wants_voice_reply("What do you know abt yourself please answer with a voice note")
    assert _wants_voice_reply("In a voice note")
    assert _wants_voice_reply("answer in a voice note")
    assert _wants_voice_reply("reply with a voice note please")
    assert _wants_voice_reply("as a voice note")
    assert _wants_voice_reply("send it as voice")
    assert _wants_voice_reply("voice note please")


def test_voice_reply_rejects_plain_text():
    assert not _wants_voice_reply("What do you know about yourself")
    assert not _wants_voice_reply("hello")
    assert not _wants_voice_reply("")
    assert not _wants_voice_reply("send me the briefing")


def test_voice_reply_rejects_voice_note_for_someone_else():
    # A voice note FOR Omar is a send-to request, not a reply request.
    assert not _wants_voice_reply("send Omar a voice note")
    assert not _wants_voice_reply("send a voice note to Sara")
    # A DM voice note is about a DM, not the reply to Sir.
    assert not _wants_voice_reply("send him a voice note on Instagram")
    assert not _wants_voice_reply("reply to the DM with a voice note")
