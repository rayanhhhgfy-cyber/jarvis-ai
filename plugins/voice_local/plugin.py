# ====================================================================
# JARVIS OMEGA — Local Voice Plugin (edge-tts + faster-whisper)
# ====================================================================
"""
Phase 10 plugin: free TTS and STT — no API keys.

  * ``voice.tts_edge`` — Microsoft Edge Read-Aloud neural voices via the
    ``edge-tts`` package. Dozens of voices, near-production quality, zero
    cost. Requires ``pip install edge-tts``.
  * ``voice.stt_whisper_local`` — local Whisper transcription via
    ``faster-whisper`` (CPU-friendly). Default model: ``base`` (~75 MB,
    downloaded on first use). Requires ``pip install faster-whisper``.

Both tools degrade gracefully if their library is missing.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Text-to-Speech (edge-tts)
# --------------------------------------------------------------------

@tool(
    name="voice.tts_edge",
    description="Synthesize speech using Microsoft Edge neural TTS. Many voices, free, no API key. Returns base64 MP3.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to speak. Max ~3000 chars per call."},
            "voice": {
                "type": "string",
                "default": "en-US-AriaNeural",
                "description": "Voice ID. Examples: en-US-GuyNeural, en-GB-SoniaNeural, zh-CN-XiaoxiaoNeural, fr-FR-DeniseNeural.",
            },
            "rate": {"type": "string", "default": "+0%", "description": "Speaking rate like '-10%' or '+20%'."},
            "pitch": {"type": "string", "default": "+0Hz"},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="voice",
)
async def voice_tts_edge(text: str, voice: str = "en-US-AriaNeural", rate: str = "+0%", pitch: str = "+0Hz") -> Dict[str, Any]:
    if len(text) > 3000:
        return {"ok": False, "error": "text too long (>3000 chars); chunk it"}
    try:
        import edge_tts  # type: ignore
    except ImportError:
        return {"ok": False, "error": "edge-tts not installed — add `edge-tts` to requirements.txt"}

    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        audio_bytes = buf.getvalue()
        if not audio_bytes:
            return {"ok": False, "error": "edge-tts returned empty audio"}
        return {
            "ok": True,
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "format": "mp3",
            "bytes": len(audio_bytes),
            "voice": voice,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="voice.tts_voices",
    description="List available edge-tts voices. Filter by language code (e.g. 'en').",
    parameters={
        "type": "object",
        "properties": {
            "language": {"type": "string", "description": "Optional BCP-47 prefix filter (e.g. 'en', 'zh', 'fr')."},
            "limit": {"type": "integer", "default": 50},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="voice",
)
async def voice_tts_voices(language: str = "", limit: int = 50) -> Dict[str, Any]:
    try:
        import edge_tts  # type: ignore
    except ImportError:
        return {"ok": False, "error": "edge-tts not installed"}
    try:
        all_voices = await edge_tts.list_voices()
        out = []
        for v in all_voices:
            if language and not v["Locale"].lower().startswith(language.lower()):
                continue
            out.append({
                "voice": v["ShortName"],
                "locale": v["Locale"],
                "gender": v["Gender"],
                "friendly": v.get("FriendlyName", v["ShortName"]),
            })
            if len(out) >= limit:
                break
        return {"ok": True, "count": len(out), "voices": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Speech-to-Text (faster-whisper, local CPU)
# --------------------------------------------------------------------

_whisper_model = None  # cached across calls


def _get_whisper_model(model_size: str = "base"):
    global _whisper_model
    if _whisper_model is not None and _whisper_model[0] == model_size:
        return _whisper_model[1]
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed — add `faster-whisper` to requirements.txt"
        )
    # Use int8 CPU compute — works on any machine, no GPU needed.
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    _whisper_model = (model_size, model)
    return model


@tool(
    name="voice.stt_whisper_local",
    description="Transcribe audio using local Whisper (faster-whisper, CPU). Default model 'base' (~75 MB, downloaded on first use). Returns transcribed text.",
    parameters={
        "type": "object",
        "properties": {
            "audio_base64": {"type": "string", "description": "Base64-encoded audio (wav/mp3/m4a/flac)."},
            "model_size": {"type": "string", "default": "base", "enum": ["tiny", "base", "small", "medium"]},
            "language": {"type": "string", "description": "Optional ISO language code (e.g. 'en')."},
        },
        "required": ["audio_base64"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="voice",
)
async def voice_stt_whisper_local(audio_base64: str, model_size: str = "base", language: str = "") -> Dict[str, Any]:
    import asyncio
    try:
        model = _get_whisper_model(model_size)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception as e:
        return {"ok": False, "error": f"invalid base64 audio: {e}"}

    # faster-whisper reads from file paths OR numpy arrays. Write a temp file.
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.close()
        # Run in a thread executor because faster-whisper is sync.
        def _transcribe():
            segments, info = model.transcribe(
                tmp.name,
                language=language or None,
                vad_filter=True,
            )
            text_parts = []
            for seg in segments:
                text_parts.append(seg.text)
            return {
                "text": "".join(text_parts).strip(),
                "language": info.language,
                "duration": round(info.duration, 2),
            }
        result = await asyncio.to_thread(_transcribe)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


PLUGIN_NAME = "voice_local"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free local TTS (Microsoft Edge neural voices) and STT (faster-whisper)."
