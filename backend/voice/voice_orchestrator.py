from __future__ import annotations

import asyncio
from typing import Optional, Callable

from shared.logger import get_logger
from backend.services.tts_service import tts_service

log = get_logger("voice_orchestrator")


class VoiceOrchestrator:
    """
    Manages the full voice pipeline:
    wake word detection -> STT -> LLM -> TTS -> playback
    """

    def __init__(self) -> None:
        self._stt_callback: Optional[Callable] = None
        self._tts_enabled: bool = True

    def set_stt_callback(self, callback: Callable) -> None:
        self._stt_callback = callback

    async def process_voice_input(self, audio_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
        if not self._stt_callback:
            log.warning("no_stt_callback_registered")
            return None
        try:
            text = await self._stt_callback(audio_bytes, sample_rate)
            log.info("voice_input_transcribed", text_len=len(text) if text else 0)
            return text
        except Exception as e:
            log.error("voice_input_failed", error=str(e))
            return None

    async def speak(self, text: str, voice: str = "jarvis") -> bytes:
        if not self._tts_enabled:
            return b""
        return await tts_service.generate_speech(text, voice=voice)

    def enable_tts(self) -> None:
        self._tts_enabled = True

    def disable_tts(self) -> None:
        self._tts_enabled = False


voice_orchestrator = VoiceOrchestrator()
