# ====================================================================
# JARVIS OMEGA — DM Media Tests (photos + voice notes)
# ====================================================================
"""
Tests for understanding photos and voice notes sent in DMs.
All HTTP is mocked — no real Groq calls, no real downloads.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from backend.services.dm_clients import _instagram_media, _messenger_media
from backend.services.dm_media import describe_image, transcribe_audio


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
