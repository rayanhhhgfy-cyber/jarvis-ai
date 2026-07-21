# Phase 18: Meeting/Audio Transcriber (REAL)
from __future__ import annotations
import base64
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="audio.transcribe", description="Transcribe a meeting/audio recording + generate summary + action items.", parameters={"type":"object","properties":{"audio_base64":{"type":"string"},"language":{"type":"string","default":"ar"}},"required":["audio_base64"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="audio_transcriber")
async def transcribe(audio_base64: str, language: str = "ar") -> Dict[str, Any]:
    # Step 1: transcribe
    from plugins.voice_local.plugin import voice_stt_whisper_local
    stt = await voice_stt_whisper_local(audio_base64=audio_base64, model_size="base", language=language)
    if not stt.get("ok"): return stt
    text = stt.get("text", "")
    if not text: return {"ok": False, "error": "no speech detected"}
    # Step 2: summarize + extract action items
    from backend.services.llm_service import llm_service
    try:
        summary = await llm_service.get_response(
            user_message="Transcript:\n" + text[:5000],
            system_instructions='Summarize this meeting in Arabic. Extract: key decisions, action items (who does what), next steps. Output Markdown.',
            inject_memory=False)
        return {"ok": True, "transcript": text, "summary": summary, "language": language}
    except Exception as e:
        return {"ok": True, "transcript": text, "summary_error": str(e)}
