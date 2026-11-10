# ====================================================================
# JARVIS OMEGA — DM Media (photos + voice notes in DMs)
# ====================================================================
"""
Understands the messages that have no text: photos and voice notes.

* ``describe_image`` — downloads a photo someone sent in a DM and asks
  Groq's vision model for a short description, so Jarvis can reply
  about what is actually in the picture instead of ignoring it.
* ``transcribe_audio`` — downloads a voice note and transcribes it with
  Groq Whisper, so Jarvis can reply to what was said.

Both are best-effort and never raise: on any failure they return None
and the caller falls back to a plain reply (or skips the message).
Downloads are capped (10 MB) so a huge file cannot stall the poll.
"""

from __future__ import annotations

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("dm_media")

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


async def _download(url: str, client: httpx.AsyncClient) -> bytes | None:
    """Download a media file (capped). Returns None on any failure."""
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            log.warning("dm_media_download_failed", status_code=resp.status_code)
            return None
        data = resp.content
        if len(data) > _MAX_DOWNLOAD_BYTES:
            log.warning("dm_media_too_large", size=len(data))
            return None
        return data
    except Exception as e:
        log.warning("dm_media_download_error", error=str(e))
        return None


async def describe_image(
    image_url: str, client: httpx.AsyncClient | None = None
) -> str | None:
    """Describe a photo in one short sentence. Returns None on failure."""
    api_key = (settings.groq_api_key or "").strip()
    if not api_key or not image_url:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        data = await _download(image_url, client)
        if not data:
            return None
        import base64

        b64 = base64.b64encode(data).decode("utf-8")
        resp = await client.post(
            _GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.groq_vision_model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this photo in one short sentence. "
                            "Say what it shows, nothing else.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }],
                "temperature": 0.3,
                "max_tokens": 120,
            },
            timeout=60.0,
        )
        if resp.status_code != 200:
            log.warning("dm_vision_failed", status_code=resp.status_code)
            return None
        choices = resp.json().get("choices") or []
        if not choices:
            return None
        text = (choices[0].get("message") or {}).get("content", "").strip()
        return text or None
    except Exception as e:
        log.warning("dm_vision_error", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


async def transcribe_audio(
    audio_url: str, client: httpx.AsyncClient | None = None
) -> str | None:
    """Transcribe a voice note. Returns the text, or None on failure."""
    api_key = (settings.groq_api_key or "").strip()
    if not api_key or not audio_url:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        data = await _download(audio_url, client)
        if not data:
            return None
        resp = await client.post(
            _GROQ_AUDIO_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("voice.mp3", data, "audio/mpeg")},
            data={"model": settings.groq_whisper_model},
            timeout=60.0,
        )
        if resp.status_code != 200:
            log.warning("dm_whisper_failed", status_code=resp.status_code)
            return None
        text = (resp.json().get("text") or "").strip()
        return text or None
    except Exception as e:
        log.warning("dm_whisper_error", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()
