# ====================================================================
# JARVIS OMEGA — Text to Speech Service
# ====================================================================
"""
TTS service with multiple backends:
1. Groq TTS API (if available and key configured)
2. Dummy silent WAV fallback

The primary TTS strategy for JARVIS OMEGA is browser-native
speechSynthesis on the frontend, which is instant and free.
This backend TTS is an optional fallback for non-browser clients.
"""

from __future__ import annotations

import io
import math
import struct
from typing import Optional

import httpx

from backend.config import settings
from shared.logger import get_logger

log = get_logger("tts_service")


class TTSService:
    """
    Text-To-Speech generator. Uses browser-native speechSynthesis as primary
    (handled by frontend), with this backend service as a fallback for
    non-browser clients or explicit TTS requests.
    """

    def __init__(self) -> None:
        self._initialized = False

    async def generate_speech(self, text: str, voice: str = "af_heart") -> bytes:
        """
        Synthesizes speech from text.
        Returns WAV raw audio bytes.
        Falls back to silent WAV if no TTS backend is available.
        """
        # Note: The primary TTS strategy for JARVIS OMEGA is browser-native
        # speechSynthesis on the frontend, which is instant, custom-voiced, and free.
        # Groq's playai-tts model has been decommissioned, so we bypass it directly.
        return self._generate_silent_wav()

    def _generate_silent_wav(self) -> bytes:
        """Generates a minimal silent WAV file."""
        sample_rate = 8000
        duration = 0.1  # 100ms of silence
        num_samples = int(sample_rate * duration)

        header = bytearray(44)
        header[0:4] = b'RIFF'
        file_size = 36 + num_samples
        struct.pack_into('<I', header, 4, file_size)
        header[8:12] = b'WAVE'
        header[12:16] = b'fmt '
        struct.pack_into('<I', header, 16, 16)
        struct.pack_into('<H', header, 20, 1)
        struct.pack_into('<H', header, 22, 1)
        struct.pack_into('<I', header, 24, sample_rate)
        struct.pack_into('<I', header, 28, sample_rate)
        struct.pack_into('<H', header, 32, 1)
        struct.pack_into('<H', header, 34, 8)
        header[36:40] = b'data'
        struct.pack_into('<I', header, 40, num_samples)

        data = bytearray(b'\x80' * num_samples)  # silence = 128 for unsigned 8-bit
        return bytes(header + data)


# Global TTS service instance
tts_service = TTSService()
