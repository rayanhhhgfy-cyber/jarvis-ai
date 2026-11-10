# ====================================================================
# JARVIS OMEGA — DM Voice Reply Tests (any-length voice replies)
# ====================================================================
"""
Tests for splitting a long DM reply into several Instagram voice
notes (each under the ~1-minute cap) and sending them in order.
All TTS/ffmpeg is mocked — no real Edge TTS or audio files.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.dm_voice import _CHUNK_CHARS, _split_text, send_voice_reply


# A realistic long DM reply (~1200 chars, several sentences).
_LONG_EN = " ".join([
    "Hey, I heard your voice note and I have been thinking about it all evening.",
    "First, the plan for Friday is still on, and I will bring the notes and the books with me when I come.",
    "Second, Omar asked about the library books, so tell him they are on the shelf now and he can pick them up tomorrow.",
    "Third, do not worry about the exam at all, we will go over everything together tonight until it all makes sense.",
    "Fourth, Sara wants to join the study group, so save her a seat next to us and send her the time and the place.",
    "Fifth, the teacher said the homework is due on Sunday, so finish the first part tonight and the second part tomorrow morning.",
    "Sixth, remember to bring your charger and your headphones, because we will be there for a long time and the phone will die.",
    "Seventh, if anything changes before Friday, message me right away and I will update everyone in the group so nobody shows up at the wrong time.",
    "Eighth, bring some water and snacks too, because we will stay in the library until the evening and the shop will be closed.",
    "Finally, call me when you are free and we can sort out the rest of it together before the weekend starts.",
])
_LONG_AR = " ".join([
    "مرحبا، سمعت رسالتك الصوتية وأنا أفكر فيها منذ المساء.",
    "أولا، خطة يوم الجمعة ما زالت قائمة وسأحضر الملاحظات والكتب معي عندما آتي.",
    "ثانيا، سأل عمر عن كتب المكتبة، فأخبره أنها على الرف الآن ويمكنه استلامها غدا.",
    "ثالثا، لا تقلق بشأن الامتحان أبدا، سنراجع كل شيء معا الليلة حتى يصبح كل شيء واضحا.",
    "رابعا، تريد سارة الانضمام إلى مجموعة الدراسة، فاحجز لها مقعدا بجانبنا وأرسل لها الوقت والمكان.",
    "خامسا، اتصل بي عندما تكون متفرغا وسنرتب باقي الأمور معا قبل أن تبدأ عطلة نهاية الأسبوع.",
    "سادسا، قال المعلم إن الواجب مستحق يوم الأحد، فأنه الجزء الأول الليلة والجزء الثاني صباح الغد.",
    "سابعا، تذكر أن تحضر الشاحن وسماعات الرأس، لأننا سنبقى هناك وقتا طويلا وستنفد بطارية الهاتف.",
    "ثامنا، إذا تغير أي شيء قبل يوم الجمعة، راسلني فورا وسأخبر الجميع في المجموعة حتى لا يأتي أحد في الوقت الخطأ.",
    "تاسعا، أحضر معك الماء وبعض الطعام، لأننا سنبقى في المكتبة حتى المساء وسيكون المتجر مغلقا.",
    "وأخيرا، لا تنس أن تحضر دفتر الملاحظات والقلم، لأننا سنكتب كل النقاط المهمة معا.",
])


# --------------------------------------------------------------------
# _split_text
# --------------------------------------------------------------------

def test_split_text_short():
    assert _split_text("Hello there.") == ["Hello there."]
    assert _split_text("   ") == []
    assert _split_text("") == []


def test_split_text_long_reply():
    """A ~1200-char reply splits into chunks of <=450, none mid-word,
    and joining the chunks gives the original back."""
    assert len(_LONG_EN) > 2 * _CHUNK_CHARS
    chunks = _split_text(_LONG_EN)
    assert len(chunks) >= 3
    assert all(len(c) <= _CHUNK_CHARS for c in chunks)
    assert " ".join(chunks) == _LONG_EN
    # No chunk cuts a sentence in half mid-word: every chunk ends with
    # a sentence mark or a whole word, never a fragment.
    for chunk in chunks:
        assert not chunk.endswith(" ")


def test_split_text_long_single_sentence():
    """One 1000-char sentence with no punctuation splits at words."""
    text = " ".join(["word"] * 200)
    assert len(text) > 2 * _CHUNK_CHARS
    chunks = _split_text(text)
    assert len(chunks) >= 3
    assert all(len(c) <= _CHUNK_CHARS for c in chunks)
    assert all(" " not in c.split()[-1] for c in chunks)  # whole words
    assert " ".join(chunks) == text


def test_split_text_arabic():
    """Arabic replies split the same way, at sentence ends."""
    assert len(_LONG_AR) > 2 * _CHUNK_CHARS
    chunks = _split_text(_LONG_AR)
    assert len(chunks) >= 2
    assert all(len(c) <= _CHUNK_CHARS for c in chunks)
    assert " ".join(chunks) == _LONG_AR


def test_split_text_huge_word():
    """One word longer than a chunk (a long URL) is hard-cut, not lost."""
    text = "x" * 1000
    chunks = _split_text(text)
    assert chunks == ["x" * _CHUNK_CHARS, "x" * _CHUNK_CHARS, "x" * 100]
    assert "".join(chunks) == text


# --------------------------------------------------------------------
# send_voice_reply
# --------------------------------------------------------------------

class _FakeVoiceClient:
    """InstagramClient stand-in: records every voice message sent."""

    def __init__(self, fail_on: int | None = None):
        self.sent: list = []
        self.fail_on = fail_on

    async def send_voice(self, thread_id, audio_path):
        self.sent.append((thread_id, audio_path))
        if self.fail_on is not None and len(self.sent) == self.fail_on:
            return {"ok": False, "reason": "send failed"}
        return {"ok": True, "message_id": f"m{len(self.sent)}"}


def _fake_synth_factory(tmp_path):
    """A fake _synthesize_mp3: a new real temp dir per chunk."""
    counter = {"n": 0}

    async def fake_synth(text):
        counter["n"] += 1
        d = tmp_path / f"c{counter['n']}"
        d.mkdir()
        p = d / "reply.mp3"
        p.write_bytes(b"fake-mp3")
        return p

    return fake_synth


async def _fake_convert(mp3_path):
    return mp3_path.with_suffix(".m4a")


@pytest.mark.asyncio
async def test_send_voice_reply_long_sends_in_order(tmp_path):
    """A long reply goes out as several voice notes, in order."""
    chunks = _split_text(_LONG_EN)
    assert len(chunks) >= 3
    client = _FakeVoiceClient()
    with (
        patch("backend.services.dm_voice._synthesize_mp3",
              new=_fake_synth_factory(tmp_path)),
        patch("backend.services.dm_voice._mp3_to_m4a", new=_fake_convert),
    ):
        assert await send_voice_reply(client, "t1", _LONG_EN) is True
    assert len(client.sent) == len(chunks)
    assert all(tid == "t1" for tid, _ in client.sent)


@pytest.mark.asyncio
async def test_send_voice_reply_synth_failure_sends_nothing(tmp_path):
    """If any chunk fails to synthesize, NO voice goes out (caller sends
    the text instead) — never a half-voice plus the full text."""
    client = _FakeVoiceClient()
    calls = {"n": 0}

    async def failing_synth(text):
        calls["n"] += 1
        if calls["n"] == 2:
            return None
        d = tmp_path / f"c{calls['n']}"
        d.mkdir()
        p = d / "reply.mp3"
        p.write_bytes(b"fake-mp3")
        return p

    text = " ".join(["This is sentence number %d, and it keeps going on." % i for i in range(40)])
    assert len(_split_text(text)) >= 2
    with (
        patch("backend.services.dm_voice._synthesize_mp3", new=failing_synth),
        patch("backend.services.dm_voice._mp3_to_m4a", new=_fake_convert),
    ):
        assert await send_voice_reply(client, "t1", text) is False
    assert client.sent == []


@pytest.mark.asyncio
async def test_send_voice_reply_send_failure_returns_false(tmp_path):
    """A failed send mid-way returns False (caller sends the text)."""
    assert len(_split_text(_LONG_EN)) >= 2
    client = _FakeVoiceClient(fail_on=2)
    with (
        patch("backend.services.dm_voice._synthesize_mp3",
              new=_fake_synth_factory(tmp_path)),
        patch("backend.services.dm_voice._mp3_to_m4a", new=_fake_convert),
    ):
        assert await send_voice_reply(client, "t1", _LONG_EN) is False
    assert len(client.sent) == 2
