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

import httpx
import pytest

from backend.services.dm_voice import _CHUNK_CHARS, _split_text, send_voice_reply


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


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


# --------------------------------------------------------------------
# Telegram voice replies (_mp3_to_ogg + send_telegram_voice_reply)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mp3_to_ogg_real_ffmpeg(tmp_path):
    """The real ffmpeg MP3 -> OGG Opus conversion works (Telegram voice
    messages need OGG Opus). Skipped where ffmpeg is missing."""
    import json
    import shutil
    import subprocess

    import backend.services.dm_voice as dm_voice

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=2",
         "-c:a", "libmp3lame", "-b:a", "64k", str(src)],
        check=True,
    )
    ogg = await dm_voice._mp3_to_ogg(src)
    assert ogg is not None and ogg.exists() and ogg.stat().st_size > 0
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(ogg)],
        capture_output=True, text=True,
    )
    assert json.loads(out.stdout)["streams"][0]["codec_name"] == "opus"


async def _fake_convert_ogg(mp3_path):
    return mp3_path.with_suffix(".ogg")


@pytest.mark.asyncio
async def test_send_telegram_voice_reply_long_sends_in_order(tmp_path):
    """A long reply goes out as several Telegram voice messages, in order."""
    from backend.services.dm_voice import send_telegram_voice_reply

    chunks = _split_text(_LONG_EN)
    assert len(chunks) >= 3
    sent = []

    async def fake_send_telegram_voice(path):
        sent.append(path)
        return True

    with (
        patch("backend.services.dm_voice._synthesize_mp3",
              new=_fake_synth_factory(tmp_path)),
        patch("backend.services.dm_voice._mp3_to_ogg", new=_fake_convert_ogg),
        patch("backend.services.telegram_notifier.send_telegram_voice",
              new=fake_send_telegram_voice),
    ):
        assert await send_telegram_voice_reply(_LONG_EN) is True
    assert len(sent) == len(chunks)
    assert all(str(p).endswith(".ogg") for p in sent)


@pytest.mark.asyncio
async def test_send_telegram_voice_reply_synth_failure_sends_nothing(tmp_path):
    """If any chunk fails to synthesize, NO Telegram voice goes out."""
    from backend.services.dm_voice import send_telegram_voice_reply

    sent = []

    async def fake_send_telegram_voice(path):
        sent.append(path)
        return True

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

    assert len(_split_text(_LONG_EN)) >= 2
    with (
        patch("backend.services.dm_voice._synthesize_mp3", new=failing_synth),
        patch("backend.services.dm_voice._mp3_to_ogg", new=_fake_convert_ogg),
        patch("backend.services.telegram_notifier.send_telegram_voice",
              new=fake_send_telegram_voice),
    ):
        assert await send_telegram_voice_reply(_LONG_EN) is False
    assert sent == []


# --------------------------------------------------------------------
# _synthesize_mp3 fallback chain (Edge classic -> Edge new server -> gTTS)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edge_tts_save_new_server_patches_and_restores_url(tmp_path):
    """When the classic endpoint fails, the new-server attempt points
    the websocket URL at api.msedgeservices.com — and restores it after."""
    import edge_tts.communicate as edge_comm
    from pathlib import Path

    import backend.services.dm_voice as dm_voice

    original_url = edge_comm.WSS_URL
    calls = {"n": 0}

    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, path):
            calls["n"] += 1
            # First attempt (classic) fails, second (new server) succeeds.
            if calls["n"] == 1:
                raise RuntimeError("403 Invalid response status")
            Path(path).write_bytes(b"fake-mp3-new-server")

    with patch("edge_tts.Communicate", FakeCommunicate):
        out = tmp_path / "reply.mp3"
        assert await dm_voice._edge_tts_save("hello", out) is False
        assert await dm_voice._edge_tts_save("hello", out, new_server=True) is True
    assert out.read_bytes() == b"fake-mp3-new-server"
    # The global URL is restored after the attempt.
    assert edge_comm.WSS_URL == original_url


@pytest.mark.asyncio
async def test_synthesize_mp3_falls_back_to_google_tts(tmp_path):
    """When both Edge endpoints fail, Google Translate TTS still
    produces the audio."""
    import backend.services.dm_voice as dm_voice

    async def fake_google_tts_save(text, out_path, client=None):
        out_path.write_bytes(b"fake-google-tts-mp3")
        return True

    with (
        patch("backend.services.dm_voice._edge_tts_save",
              new=AsyncMock(return_value=False)),
        patch("backend.services.dm_voice._google_tts_save", new=fake_google_tts_save),
    ):
        result = await dm_voice._synthesize_mp3("hello there")
    assert result is not None and result.exists()
    assert result.read_bytes() == b"fake-google-tts-mp3"


@pytest.mark.asyncio
async def test_synthesize_mp3_all_engines_fail_returns_none(tmp_path):
    """When every engine fails, _synthesize_mp3 returns None (and the
    temp dir is cleaned up, not orphaned)."""
    import backend.services.dm_voice as dm_voice

    with (
        patch("backend.services.dm_voice._edge_tts_save",
              new=AsyncMock(return_value=False)),
        patch("backend.services.dm_voice._google_tts_save",
              new=AsyncMock(return_value=False)),
    ):
        assert await dm_voice._synthesize_mp3("hello there") is None


@pytest.mark.asyncio
async def test_google_tts_save_chunks_and_picks_language(tmp_path):
    """Google Translate TTS: a long reply is split into short requests
    and the audio joined; Arabic gets tl=ar, English gets tl=en.
    (The real endpoint was verified with curl: valid MP3s for both
    languages that convert cleanly to OGG — httpx cannot reach it from
    this sandbox, so the transport is mocked here.)"""
    import backend.services.dm_voice as dm_voice

    seen_langs: list[str] = []
    seen_chunks: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        seen_langs.append(query.get("tl", ""))
        seen_chunks.append(query.get("q", ""))
        return httpx.Response(200, content=b"fake-mp3-chunk")

    long_en = (
        "Hello Rayyan, this is Jarvis speaking to you in English. "
        "I can answer your messages with real voice notes now."
    )
    en = tmp_path / "en.mp3"
    assert await dm_voice._google_tts_save(
        long_en, en, client=_mock_client(handler)
    ) is True
    assert en.exists() and en.stat().st_size > 0
    # Split into short chunks, all in English, joined back together.
    assert len(seen_chunks) >= 2
    assert all(len(c) <= 100 for c in seen_chunks)
    assert all(lang == "en" for lang in seen_langs)
    assert en.read_bytes() == b"fake-mp3-chunk" * len(seen_chunks)

    seen_langs.clear()
    seen_chunks.clear()
    ar = tmp_path / "ar.mp3"
    assert await dm_voice._google_tts_save(
        "مرحبا ريان، كيف حالك اليوم؟", ar, client=_mock_client(handler)
    ) is True
    assert ar.exists() and ar.stat().st_size > 0
    assert seen_langs == ["ar"]


@pytest.mark.asyncio
async def test_google_tts_save_http_error_returns_false(tmp_path):
    """A non-200 from Google Translate TTS fails the whole save."""
    import backend.services.dm_voice as dm_voice

    out = tmp_path / "out.mp3"
    assert await dm_voice._google_tts_save(
        "hello", out, client=_mock_client(lambda r: httpx.Response(403))
    ) is False
    assert not out.exists()
