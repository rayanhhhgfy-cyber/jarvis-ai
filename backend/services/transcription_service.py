# ====================================================================
# JARVIS OMEGA — Transcription Service (Groq Whisper)
# ====================================================================
"""
Transcribes speech to text using the Groq Whisper API. Supports file path
and raw audio buffer uploads, returning structured text transcriptions.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("transcription_service")


class TranscriptionService:
    """
    Communicates with Groq Cloud Audio Transcriptions API to perform fast,
    accurate Whisper-based speech-to-text conversions.
    """

    def __init__(self) -> None:
        self._api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe_file(self, file_path: str | Path, language: Optional[str] = None) -> str:
        """Transcribe an audio file on disk."""
        path = Path(file_path)
        if not path.exists():
            log.error("audio_file_not_found", path=str(path))
            return ""

        try:
            with open(path, "rb") as audio_file:
                files = {
                    "file": (path.name, audio_file, "audio/wav" if path.suffix == ".wav" else "audio/mpeg")
                }
                return await self._call_groq_api(files, language)
        except Exception as e:
            log.error("transcribe_file_failed", file=str(path), error=str(e))
            return ""

    async def transcribe_bytes(self, audio_bytes: bytes, filename: str = "audio.wav", language: Optional[str] = None) -> str:
        """Transcribe raw audio bytes from memory."""
        try:
            # Detect content type from filename
            if filename.endswith(".webm"):
                content_type = "audio/webm"
            elif filename.endswith(".mp3") or filename.endswith(".mpeg"):
                content_type = "audio/mpeg"
            elif filename.endswith(".m4a"):
                content_type = "audio/mp4"
            elif filename.endswith(".ogg"):
                content_type = "audio/ogg"
            else:
                content_type = "audio/wav"

            files = {
                "file": (filename, io.BytesIO(audio_bytes), content_type)
            }
            return await self._call_groq_api(files, language)
        except Exception as e:
            log.error("transcribe_bytes_failed", filename=filename, error=str(e))
            return ""

    async def _call_groq_api(self, files: dict, language: Optional[str] = None) -> str:
        """Performs the HTTP request to Groq Cloud endpoint."""
        api_key = settings.groq_api_key
        if not api_key:
            log.warning("groq_api_key_missing_mocking_transcription")
            return "[Mock Transcript: Please configure GROQ_API_KEY in your environment]"

        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        data = {
            "model": settings.whisper_model,
            "response_format": "json",
        }
        if language:
            data["language"] = language

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    self._api_url,
                    headers=headers,
                    data=data,
                    files=files,
                )

                if response.status_code != 200:
                    log.error("groq_api_error", status_code=response.status_code, body=response.text)
                    return ""

                result_json = response.json()
                text = result_json.get("text", "").strip()
                log.info("audio_transcribed_successfully", length=len(text))
                return text

            except httpx.HTTPError as he:
                log.error("groq_api_http_failed", error=str(he))
                return ""


# Global transcription service instance
transcription_service = TranscriptionService()
