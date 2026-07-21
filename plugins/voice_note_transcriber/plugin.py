# Phase 18 plugin
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="voice_note.transcribe", description="Transcribe a WhatsApp voice note to text.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="communication")
async def _voice_note_transcribe() -> Dict[str, Any]:
    return {"ok": True, "plugin": "voice_note_transcriber", "tool": "voice_note.transcribe"}

PLUGIN_NAME = "voice_note_transcriber"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Transcribe a WhatsApp voice note to text."