"""
JARVIS OMEGA — TTS Service (Local-only via pyttsx3)
====================================================
Fully offline text-to-speech using pyttsx3.
Falls back to silent WAV if pyttsx3 is unavailable.
No cloud dependencies (edge_tts removed per user request).
"""

from __future__ import annotations

import asyncio
import io
import struct
import threading
from typing import Optional

from shared.logger import get_logger

log = get_logger("tts_service")


class TTSService:
    """Local-only TTS service using pyttsx3."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        self._available = False
        self._probe_engine()

    def _probe_engine(self) -> None:
        """Try to initialise pyttsx3 at import time to verify availability."""
        try:
            import pyttsx3  # type: ignore
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            self._available = True
            log.info("tts_pyttsx3_probe_ok", voices_found=len(voices))
            del engine
        except Exception as e:
            log.warning("tts_pyttsx3_unavailable", error=str(e), hint="pip install pyttsx3")
            self._available = False

    async def generate_speech(self, text: str, voice: str = "jarvis") -> bytes:
        """
        Generate speech audio.

        Since pyttsx3 is a synchronous blocking engine that plays directly
        to speakers, we run it in a thread executor and return a tiny WAV
        (the real audio is played through the system speakers).
        """
        if not self._available:
            log.debug("tts_unavailable_returning_silent")
            return self._generate_silent_wav()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._speak_blocking, text)
            log.info("tts_spoken", chars=len(text))
        except Exception as e:
            log.error("tts_speak_failed", error=str(e))

        # Return a minimal WAV so callers expecting bytes still work
        return self._generate_silent_wav()

    def _speak_blocking(self, text: str) -> None:
        """Synchronously speak text through system speakers inside worker thread."""
        with self._lock:
            has_com = False
            try:
                import pyttsx3  # type: ignore
                try:
                    import pythoncom  # type: ignore
                    pythoncom.CoInitialize()
                    has_com = True
                except Exception:
                    pass

                try:
                    engine = pyttsx3.init()
                    voices = engine.getProperty("voices")
                    # Prefer a male English voice
                    for v in voices:
                        if "male" in v.name.lower() or "david" in v.name.lower():
                            engine.setProperty("voice", v.id)
                            break
                    engine.setProperty("rate", 170)
                    engine.setProperty("volume", 0.95)
                    engine.say(text)
                    engine.runAndWait()
                    # Explicit cleanup
                    del engine
                finally:
                    if has_com:
                        pythoncom.CoUninitialize()
            except Exception as e:
                log.error("tts_speak_blocking_failed", error=str(e))

    @staticmethod
    def _generate_silent_wav() -> bytes:
        """Generate a minimal valid WAV file (silent)."""
        sample_rate = 8000
        duration = 0.1
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
        data = bytearray(b'\x80' * num_samples)
        return bytes(header + data)


tts_service = TTSService()
