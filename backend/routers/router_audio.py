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


# --------------------------------------------------------------------
# Voice call (Talk): one spoken turn with Jarvis.
# --------------------------------------------------------------------
# The dashboard's Talk page records Rayyan's voice in the browser and
# posts it here. One request = one turn: Whisper transcribes, the chat
# brain answers, Edge/Google TTS speaks the reply back as an MP3.
# All three layers are the proven ones (the same code that powers the
# Telegram voice notes) — the /tts route above returns silent audio.
_VOICE_TALK_SYSTEM = (
    "You are Jarvis, Rayyan's AI assistant, talking to him by voice on "
    "a live call. Keep every reply short — 1 to 3 sentences, spoken "
    "naturally, like a real conversation. Never write '[Voice note]' or "
    "announce anything about voice. Answer in ONE language: the language "
    "Rayyan used (Arabic or English). Never answer in both languages in "
    "the same reply. If you do not know something, say so — never invent "
    "facts, dates, prices, names, or scores."
)


@router.post("/talk")
async def voice_talk(file: UploadFile = File(...)):
    """One spoken turn: audio in, Jarvis's spoken reply (MP3) out.

    Returns {"ok", "transcript", "reply", "audio_base64", "audio_mime"}.
    When nothing could be heard, the reply is a short 'didn't catch that'
    spoken the same way, so the call keeps flowing.
    """
    import base64
    import shutil

    from backend.services.dm_voice import _synthesize_mp3
    from backend.services.llm_service import llm_service

    try:
        audio_bytes = await file.read()
    except Exception as e:
        log.error("voice_talk_read_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the uploaded audio.",
        )
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty audio upload.",
        )

    transcript = await transcription_service.transcribe_bytes(
        audio_bytes=audio_bytes,
        filename=file.filename or "recording.webm",
    )
    transcript = (transcript or "").strip()

    if not transcript:
        reply = "Sorry, I didn't catch that. Could you say it again?"
    else:
        log.info("voice_talk_heard", chars=len(transcript))
        try:
            reply = await llm_service.get_response(
                transcript,
                chat_history=[],
                inject_memory=True,
                system_instructions=_VOICE_TALK_SYSTEM,
            )
        except Exception as e:
            log.error("voice_talk_brain_failed", error=str(e))
            reply = "Sorry, something went wrong on my side. Try again?"

    reply = (reply or "").strip() or "Sorry, I didn't catch that."
    mp3_path = await _synthesize_mp3(reply)
    audio_b64 = ""
    if mp3_path is not None:
        try:
            audio_b64 = base64.b64encode(mp3_path.read_bytes()).decode("ascii")
        except Exception as e:
            log.warning("voice_talk_audio_read_failed", error=str(e))
        finally:
            shutil.rmtree(mp3_path.parent, ignore_errors=True)
    return {
        "ok": True,
        "transcript": transcript,
        "reply": reply,
        "audio_base64": audio_b64,
        "audio_mime": "audio/mpeg",
    }
