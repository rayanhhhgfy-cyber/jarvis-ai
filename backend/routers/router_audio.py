# ====================================================================
# JARVIS OMEGA — Audio Router (STT & TTS)
# ====================================================================
"""
Audio processing routes: transcribing uploaded audio file chunks (STT) and
synthesizing output voice responses (TTS).
"""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Response, status

from backend.services.transcription_service import transcription_service
from backend.services.tts_service import tts_service
from shared.logger import get_logger

log = get_logger("router_audio")
router = APIRouter(prefix="/api/audio", tags=["Audio"])


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(..., description="Audio file payload (WAV or MP3)"),
    language: str = Query(None, description="Optional ISO language code hint"),
):
    """Uploads and transcribes voice recording commands via Whisper."""
    log.info("audio_transcribe_upload_received", file_name=file.filename)
    try:
        content = await file.read()
        text = await transcription_service.transcribe_bytes(
            audio_bytes=content,
            filename=file.filename or "recording.wav",
            language=language,
        )
        return {"text": text}
    except Exception as e:
        log.error("upload_transcription_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to transcribe audio: {str(e)}",
        )


@router.post("/tts")
async def generate_text_to_speech(
    text: str = Query(..., description="Text content to synthesize"),
    voice: str = Query("af_heart", description="Voice profile to generate"),
):
    """Synthesizes text into WAV audio bytes using Kokoro-82M."""
    log.info("tts_request_received", text_len=len(text), voice=voice)
    try:
        audio_data = await tts_service.generate_speech(text, voice=voice)
        return Response(
            content=audio_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=tts.wav"
            }
        )
    except Exception as e:
        log.error("tts_generation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synthesize speech: {str(e)}",
        )
