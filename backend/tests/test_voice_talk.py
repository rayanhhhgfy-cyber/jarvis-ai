# Tests for the voice call (Talk) endpoint: POST /api/audio/talk.
# One spoken turn: audio in, Jarvis's spoken reply (MP3) out.

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.router_audio import router as audio_router


def _audio_app() -> TestClient:
    app = FastAPI()
    app.include_router(audio_router)
    return TestClient(app)


@pytest.mark.asyncio
async def test_voice_talk_turn(tmp_path, monkeypatch):
    """A spoken turn returns the transcript, the reply, and real audio."""
    fake_mp3 = tmp_path / "reply.mp3"
    fake_mp3.write_bytes(b"FAKE-MP3-BYTES")

    async def _fake_transcribe(audio_bytes, filename="audio.wav", language=None):
        return "what time is it"

    async def _fake_reply(*args, **kwargs):
        return "It is five o'clock."

    async def _fake_tts(text):
        return fake_mp3

    with (
        patch(
            "backend.services.transcription_service.transcription_service.transcribe_bytes",
            new=_fake_transcribe,
        ),
        patch(
            "backend.services.llm_service.llm_service.get_response",
            new=_fake_reply,
        ),
        patch(
            "backend.services.dm_voice._synthesize_mp3",
            new=_fake_tts,
        ),
    ):
        resp = _audio_app().post(
            "/api/audio/talk",
            files={"file": ("recording.webm", b"FAKE-WEBM", "audio/webm")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["transcript"] == "what time is it"
    assert data["reply"] == "It is five o'clock."
    assert data["audio_mime"] == "audio/mpeg"
    import base64

    assert base64.b64decode(data["audio_base64"]) == b"FAKE-MP3-BYTES"


@pytest.mark.asyncio
async def test_voice_talk_unheard(tmp_path, monkeypatch):
    """When nothing is heard, the reply is a spoken 'didn't catch that'."""
    fake_mp3 = tmp_path / "reply.mp3"
    fake_mp3.write_bytes(b"FAKE-MP3-BYTES")

    async def _fake_transcribe(audio_bytes, filename="audio.wav", language=None):
        return ""

    async def _fake_tts(text):
        assert "didn't catch" in text
        return fake_mp3

    with (
        patch(
            "backend.services.transcription_service.transcription_service.transcribe_bytes",
            new=_fake_transcribe,
        ),
        patch(
            "backend.services.dm_voice._synthesize_mp3",
            new=_fake_tts,
        ),
    ):
        resp = _audio_app().post(
            "/api/audio/talk",
            files={"file": ("recording.webm", b"FAKE-WEBM", "audio/webm")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["transcript"] == ""
    assert "didn't catch" in data["reply"]
    assert data["audio_base64"] != ""


@pytest.mark.asyncio
async def test_voice_talk_language_hint(tmp_path, monkeypatch):
    """A language hint reaches Whisper so short English is not mis-heard."""
    fake_mp3 = tmp_path / "reply.mp3"
    fake_mp3.write_bytes(b"FAKE-MP3-BYTES")
    seen = {}

    async def _fake_transcribe(audio_bytes, filename="audio.wav", language=None):
        seen["language"] = language
        return "hey Jarvis how are you"

    async def _fake_reply(*args, **kwargs):
        return "I am doing great, thanks."

    async def _fake_tts(text):
        return fake_mp3

    with (
        patch(
            "backend.services.transcription_service.transcription_service.transcribe_bytes",
            new=_fake_transcribe,
        ),
        patch(
            "backend.services.llm_service.llm_service.get_response",
            new=_fake_reply,
        ),
        patch(
            "backend.services.dm_voice._synthesize_mp3",
            new=_fake_tts,
        ),
    ):
        resp = _audio_app().post(
            "/api/audio/talk?language=en",
            files={"file": ("recording.webm", b"FAKE-WEBM", "audio/webm")},
        )
    assert resp.status_code == 200
    assert seen["language"] == "en"
    assert resp.json()["reply"] == "I am doing great, thanks."


@pytest.mark.asyncio
async def test_voice_talk_empty_audio_rejected():
    """An empty audio upload is a 400, not a silent turn."""
    resp = _audio_app().post(
        "/api/audio/talk",
        files={"file": ("recording.webm", b"", "audio/webm")},
    )
    assert resp.status_code == 400
