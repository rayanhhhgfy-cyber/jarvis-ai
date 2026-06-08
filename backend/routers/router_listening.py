from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.services.transcription_service import transcription_service
from backend.services.voice_listener import voice_listener
from shared.logger import get_logger

log = get_logger("router_listening")
router = APIRouter(prefix="/api/listening", tags=["Voice Listening"])


async def _transcribe_audio(audio_bytes: bytes) -> str:
    return await transcription_service.transcribe_bytes(audio_bytes)


@router.post("/start")
async def start_listening() -> Dict[str, Any]:
    voice_listener.set_transcribe_callback(_transcribe_audio)
    voice_listener.start()
    return {"status": "listening", "enabled": True}


@router.post("/stop")
async def stop_listening() -> Dict[str, Any]:
    voice_listener.stop()
    return {"status": "stopped", "enabled": False}


@router.get("/status")
async def get_listening_status() -> Dict[str, Any]:
    return {"listening": voice_listener.is_running, "enabled": voice_listener.is_running}
