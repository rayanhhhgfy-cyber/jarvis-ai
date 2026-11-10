# ====================================================================
# JARVIS OMEGA — DM Media Tests (photos + voice notes)
# ====================================================================
"""
Tests for understanding photos and voice notes sent in DMs.
All HTTP is mocked — no real Groq calls, no real downloads.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services.dm_clients import _instagram_media, _messenger_media
from backend.services.dm_media import (
    describe_image,
    describe_image_bytes,
    describe_video,
    transcribe_audio,
    transcribe_audio_bytes,
)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------
# Media extraction from platform messages
# --------------------------------------------------------------------

def test_instagram_media_photo():
    last = SimpleNamespace(
        item_type="media",
        media=SimpleNamespace(
            image_versions2={"candidates": [{"url": "https://cdn.example/p.jpg"}]},
            video_versions=[],
        ),
    )
    assert _instagram_media(last) == ("https://cdn.example/p.jpg", "photo")


def test_instagram_media_voice():
    last = SimpleNamespace(
        item_type="voice_media",
        voice_media=SimpleNamespace(
            media=SimpleNamespace(audio={"audio_src": "https://cdn.example/v.mp3"})
        ),
    )
    assert _instagram_media(last) == ("https://cdn.example/v.mp3", "voice")


def test_instagram_media_text_is_none():
    last = SimpleNamespace(item_type="text", media=None, voice_media=None)
    assert _instagram_media(last) == (None, None)


def test_messenger_media_photo():
    node = {
        "attachments": [
            {"mime_type": "image/jpeg", "url": "https://fb.example/img.jpg"},
        ],
    }
    assert _messenger_media(node) == ("https://fb.example/img.jpg", "photo")


def test_messenger_media_none():
    assert _messenger_media({}) == (None, None)
    assert _messenger_media({"attachments": [{"mime_type": "text/plain"}]}) == (None, None)


# --------------------------------------------------------------------
# describe_image (Groq vision, mocked)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_describe_image_ok(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.groq.com" in str(request.url):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "A cat sitting on a couch."}}],
            })
        # The image download.
        return httpx.Response(200, content=b"\xff\xd8\xff fake-jpeg")

    result = await describe_image("https://cdn.example/p.jpg", client=_mock_client(handler))
    assert result == "A cat sitting on a couch."


@pytest.mark.asyncio
async def test_describe_image_no_key(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "")
    assert await describe_image("https://cdn.example/p.jpg", client=_mock_client(lambda r: httpx.Response(200))) is None


@pytest.mark.asyncio
async def test_describe_image_vision_error(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.groq.com" in str(request.url):
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, content=b"\xff\xd8\xff fake-jpeg")

    assert await describe_image("https://cdn.example/p.jpg", client=_mock_client(handler)) is None


# --------------------------------------------------------------------
# transcribe_audio (Groq Whisper, mocked)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_audio_ok(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.groq.com" in str(request.url):
            return httpx.Response(200, json={"text": "hello, are you there?"})
        return httpx.Response(200, content=b"fake-audio-bytes")

    result = await transcribe_audio("https://cdn.example/v.mp3", client=_mock_client(handler))
    assert result == "hello, are you there?"


@pytest.mark.asyncio
async def test_transcribe_audio_no_key(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "")
    assert await transcribe_audio("https://cdn.example/v.mp3", client=_mock_client(lambda r: httpx.Response(200))) is None


# --------------------------------------------------------------------
# transcribe_audio — long voice notes (stream + split + join)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_audio_long_joins_segments(monkeypatch, tmp_path):
    """A voice note too big for one download is streamed, split into
    pieces, transcribed piece by piece, and joined — heard in full."""
    import backend.services.dm_media as dm_media

    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")
    # Shrink the fast-path cap so a small file takes the long path.
    monkeypatch.setattr(dm_media, "_MAX_DOWNLOAD_BYTES", 10)
    transcripts = iter(["part one", "part two"])

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.groq.com" in str(request.url):
            return httpx.Response(200, json={"text": next(transcripts)})
        return httpx.Response(200, content=b"fake-audio-bytes" * 10)

    async def fake_split(src, tmpdir):
        seg1 = tmp_path / "seg_001.mp3"
        seg2 = tmp_path / "seg_002.mp3"
        seg1.write_bytes(b"fake-segment-one")
        seg2.write_bytes(b"fake-segment-two")
        return [seg1, seg2]

    monkeypatch.setattr(dm_media, "_split_audio", fake_split)
    result = await transcribe_audio(
        "https://cdn.example/long.mp3", client=_mock_client(handler)
    )
    assert result == "part one part two"


@pytest.mark.asyncio
async def test_transcribe_audio_long_split_fails_returns_none(monkeypatch):
    """When a long voice note cannot be split, transcription returns None
    (same as before — no crash, no partial transcript)."""
    import backend.services.dm_media as dm_media

    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")
    monkeypatch.setattr(dm_media, "_MAX_DOWNLOAD_BYTES", 10)
    monkeypatch.setattr(dm_media, "_split_audio", AsyncMock(return_value=[]))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"fake-audio-bytes" * 10)

    assert await transcribe_audio(
        "https://cdn.example/long.mp3", client=_mock_client(handler)
    ) is None


@pytest.mark.asyncio
async def test_split_audio_real_ffmpeg(tmp_path, monkeypatch):
    """The real ffmpeg split works: a 3-second clip cut into 1-second
    pieces comes back as 3 segments. Skipped where ffmpeg is missing."""
    import shutil
    import subprocess

    import backend.services.dm_media as dm_media

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3",
         "-c:a", "libmp3lame", "-b:a", "64k", str(src)],
        check=True,
    )
    monkeypatch.setattr(dm_media, "_SEGMENT_SECONDS", 1)
    segments = await dm_media._split_audio(src, tmp_path)
    # ffmpeg can emit one extra trailing segment for encoder padding,
    # so the count is at least 3, not exactly 3.
    assert len(segments) >= 3
    assert all(s.exists() and s.stat().st_size > 0 for s in segments)


@pytest.mark.asyncio
async def test_split_audio_no_ffmpeg(monkeypatch, tmp_path):
    """Without ffmpeg, splitting returns [] (the caller falls back)."""
    import shutil

    import backend.services.dm_media as dm_media

    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert await dm_media._split_audio(tmp_path / "voice.bin", tmp_path) == []


# --------------------------------------------------------------------
# transcribe_audio_bytes (Telegram voice notes arrive as bytes)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_audio_bytes_ok(monkeypatch):
    """Bytes in -> Whisper text out, no download needed."""
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.groq.com" in str(request.url)
        return httpx.Response(200, json={"text": "what do you recommend"})

    result = await transcribe_audio_bytes(b"fake-ogg-bytes", client=_mock_client(handler))
    assert result == "what do you recommend"


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_no_key(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "")
    assert await transcribe_audio_bytes(
        b"fake-ogg-bytes", client=_mock_client(lambda r: httpx.Response(200))
    ) is None


# --------------------------------------------------------------------
# describe_image_bytes + describe_video (Telegram photos and videos)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_describe_image_bytes_ok(monkeypatch):
    """Photo bytes in -> Groq vision text out, no download needed."""
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.groq.com" in str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "A cat sitting on a couch."}}],
        })

    result = await describe_image_bytes(b"fake-jpeg-bytes", client=_mock_client(handler))
    assert result == "A cat sitting on a couch."


@pytest.mark.asyncio
async def test_describe_image_bytes_no_key(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "")
    assert await describe_image_bytes(
        b"fake-jpeg-bytes", client=_mock_client(lambda r: httpx.Response(200))
    ) is None


@pytest.mark.asyncio
async def test_describe_video_real_ffmpeg(tmp_path, monkeypatch):
    """A real video is described from frames spread across it (vision
    mocked — the test proves the frame extraction + joining)."""
    import shutil
    import subprocess

    import backend.services.dm_media as dm_media

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")
    video = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=4:size=128x128:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )
    seen = {"n": 0}

    async def fake_vision(data, client):
        seen["n"] += 1
        return f"a test frame {seen['n']}"

    monkeypatch.setattr(dm_media, "_vision_bytes", fake_vision)
    # Pass a mock client: a real httpx client cannot even be created in
    # this sandbox (the proxy env vars break httpx's URL parsing), and
    # vision is mocked anyway, so the client is never used for real.
    result = await describe_video(
        video.read_bytes(), client=_mock_client(lambda r: httpx.Response(200))
    )
    assert result is not None
    # Four frames spread across a 4-second clip.
    assert seen["n"] == 4
    assert "frame 1: a test frame 1" in result
    assert "frame 4: a test frame 4" in result


@pytest.mark.asyncio
async def test_describe_video_no_ffmpeg(monkeypatch):
    """Without ffmpeg, a video cannot be described (caller falls back)."""
    import shutil

    import backend.services.dm_media as dm_media

    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "gsk-test")
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert await describe_video(b"fake-video-bytes") is None


@pytest.mark.asyncio
async def test_describe_video_no_key(monkeypatch):
    monkeypatch.setattr("backend.services.dm_media.settings.groq_api_key", "")
    assert await describe_video(b"fake-video-bytes") is None
