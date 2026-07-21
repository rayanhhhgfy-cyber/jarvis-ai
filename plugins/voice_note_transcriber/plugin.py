# Phase 18: Voice Note Transcriber (REAL)
from __future__ import annotations
import base64
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="voice_note.transcribe", description="Transcribe a WhatsApp voice note (base64 audio) to text.", parameters={"type":"object","properties":{"audio_base64":{"type":"string"},"language":{"type":"string","default":"ar"}},"required":["audio_base64"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="voice_note_transcriber")
async def transcribe(audio_base64: str, language: str = "ar") -> Dict[str, Any]:
    from plugins.voice_local.plugin import voice_stt_whisper_local
    result = await voice_stt_whisper_local(audio_base64=audio_base64, model_size="base", language=language)
    return result
