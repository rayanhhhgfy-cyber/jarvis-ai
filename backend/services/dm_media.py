# ====================================================================
# JARVIS OMEGA — DM Media (photos + voice notes in DMs)
# ====================================================================
"""
Understands the messages that have no text: photos and voice notes.

* ``describe_image`` — downloads a photo someone sent in a DM and asks
  Groq's vision model for a short description, so Jarvis can reply
  about what is actually in the picture instead of ignoring it.
* ``transcribe_audio`` — downloads a voice note and transcribes it with
  Groq Whisper, so Jarvis can reply to what was said. A voice note of
  any length works: a short one is transcribed in a single call, and a
  long one is split into 5-minute pieces (ffmpeg) and transcribed piece
  by piece, then joined — nothing is cut off.

Both are best-effort and never raise: on any failure they return None
and the caller falls back to a plain reply (or skips the message).
Downloads are capped (10 MB) so a huge file cannot stall the poll —
except a voice note, which streams to disk and is split instead.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("dm_media")

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
# A streamed voice note is never kept whole in memory; this disk cap is
# only a safety net against a runaway download (about 8 hours of voice).
_MAX_LONG_AUDIO_BYTES = 200 * 1024 * 1024
# Long voice notes are transcribed in pieces of this length.
_SEGMENT_SECONDS = 300


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


async def _whisper_bytes(data: bytes, client: httpx.AsyncClient) -> str | None:
    """One Groq Whisper call for an audio blob. Returns text or None."""
    api_key = (settings.groq_api_key or "").strip()
    if not api_key or not data:
        return None
    try:
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


async def _split_audio(src: Path, tmpdir: Path) -> list[Path]:
    """Split an audio file into 5-minute MP3 segments with ffmpeg.

    Returns the segment paths in order, or [] when ffmpeg is missing
    or the file cannot be split. (ffmpeg is installed on Render by the
    build command, same as the voice-reply converter.)
    """
    if not shutil.which("ffmpeg"):
        log.warning("dm_whisper_no_ffmpeg")
        return []
    pattern = str(tmpdir / "seg_%03d.mp3")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error",
            "-i", str(src),
            "-f", "segment", "-segment_time", str(_SEGMENT_SECONDS),
            "-c:a", "libmp3lame", "-b:a", "64k",
            pattern,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("dm_whisper_split_failed", error=stderr.decode()[:200])
            return []
    except Exception as e:
        log.warning("dm_whisper_split_failed", error=str(e))
        return []
    return sorted(tmpdir.glob("seg_*.mp3"))


async def _transcribe_long(
    audio_url: str, client: httpx.AsyncClient
) -> str | None:
    """Transcribe a voice note too big for one download, in pieces.

    Streams the file to disk (never whole in memory), splits it into
    5-minute segments, transcribes each with Whisper, and joins the
    transcripts. Returns None when the file cannot be fetched or split.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="jarvis_voice_in_"))
    try:
        src = tmpdir / "voice.bin"
        size = 0
        try:
            async with client.stream(
                "GET", audio_url, follow_redirects=True
            ) as resp:
                if resp.status_code != 200:
                    log.warning(
                        "dm_media_download_failed", status_code=resp.status_code
                    )
                    return None
                with open(src, "wb") as f:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        size += len(chunk)
                        if size > _MAX_LONG_AUDIO_BYTES:
                            log.warning("dm_media_too_large", size=size)
                            return None
                        f.write(chunk)
        except Exception as e:
            log.warning("dm_media_download_error", error=str(e))
            return None
        if size == 0:
            return None
        segments = await _split_audio(src, tmpdir)
        if not segments:
            return None
        parts: list[str] = []
        for seg in segments:
            text = await _whisper_bytes(seg.read_bytes(), client)
            if text:
                parts.append(text)
        joined = " ".join(parts).strip()
        return joined or None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def transcribe_audio_bytes(
    data: bytes, client: httpx.AsyncClient | None = None
) -> str | None:
    """Transcribe voice-note bytes already in memory (Telegram voice
    messages arrive this way — their download URL carries the bot
    token, so the bytes are fetched first and the URL never reaches
    this module). Returns text, or None on failure."""
    api_key = (settings.groq_api_key or "").strip()
    if not api_key or not data:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        return await _whisper_bytes(data, client)
    except Exception as e:
        log.warning("dm_whisper_error", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


async def transcribe_audio(
    audio_url: str, client: httpx.AsyncClient | None = None
) -> str | None:
    """Transcribe a voice note, however long. Returns text, or None on failure.

    Short notes take the fast path (one download + one Whisper call).
    When the file is too big for one download, it is streamed to disk
    and transcribed in 5-minute pieces instead — a long voice note is
    heard in full, never cut off.
    """
    api_key = (settings.groq_api_key or "").strip()
    if not api_key or not audio_url:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)
    assert client is not None
    try:
        data = await _download(audio_url, client)
        if data:
            return await _whisper_bytes(data, client)
        return await _transcribe_long(audio_url, client)
    except Exception as e:
        log.warning("dm_whisper_error", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()
