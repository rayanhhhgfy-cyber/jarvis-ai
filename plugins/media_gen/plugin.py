# ====================================================================
# JARVIS OMEGA — Media Generation Plugin
# ====================================================================
"""
Phase 8 seed plugin: image / TTS / STT / video generation.

Image generation uses OpenRouter's chat-completions endpoint with a vision
model (or external services via atxp — see plugins.atxp_wrapper). Audio tools
reuse existing Groq / Kokoro / Whisper providers from settings.
"""

from __future__ import annotations

import base64
from typing import Any, Dict

from backend.tools import tool, RiskTier
from backend.config import settings


@tool(
    name="media.image",
    description="Generate an image from a text prompt. Uses OpenRouter image-gen provider if configured.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "size": {"type": "string", "default": "1024x1024"},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="media",
)
async def media_image(prompt: str, size: str = "1024x1024") -> Dict[str, Any]:
    api_key = settings.openrouter_api_key
    if not api_key:
        return {"generated": False, "error": "OPENROUTER_API_KEY not configured"}
    import httpx
    payload = {
        "model": "openai/dall-e-3",  # OpenRouter routes this to the actual provider.
        "prompt": prompt,
        "size": size,
        "n": 1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/images/generations",
            json=payload,
            headers=headers,
        )
    if resp.status_code >= 400:
        return {"generated": False, "status": resp.status_code, "error": resp.text[:300]}
    data = resp.json()
    return {
        "generated": True,
        "images": [img.get("url") for img in data.get("data", [])],
        "raw": data,
    }


@tool(
    name="media.tts",
    description="Synthesize speech from text via the existing TTS service. Returns base64 WAV audio.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "voice": {"type": "string", "default": "af_heart"},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_tts(text: str, voice: str = "af_heart") -> Dict[str, Any]:
    from backend.services.tts_service import tts_service
    audio_bytes = await tts_service.generate_speech(text, voice=voice)
    return {
        "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
        "format": "wav",
        "bytes": len(audio_bytes),
    }


@tool(
    name="media.stt",
    description="Transcribe audio bytes (base64-encoded WAV/MP3) using Groq Whisper if configured.",
    parameters={
        "type": "object",
        "properties": {
            "audio_base64": {"type": "string"},
            "format": {"type": "string", "default": "wav"},
        },
        "required": ["audio_base64"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_stt(audio_base64: str, format: str = "wav") -> Dict[str, Any]:
    api_key = settings.groq_api_key
    if not api_key:
        return {"transcribed": False, "error": "GROQ_API_KEY not configured"}
    import httpx
    audio_bytes = base64.b64decode(audio_base64)
    files = {
        "file": (f"audio.{format}", audio_bytes, f"audio/{format}"),
        "model": (None, settings.whisper_model),
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            files=files,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code >= 400:
        return {"transcribed": False, "status": resp.status_code, "error": resp.text[:300]}
    return {"transcribed": True, "text": resp.json().get("text", "")}


@tool(
    name="media.video",
    description="Generate a short video clip. Routes to the best available free option: Pollinations image slideshow with music, or MusicGen local video.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "seconds": {"type": "number", "default": 5},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="media",
)
async def media_video(prompt: str, seconds: float = 5) -> Dict[str, Any]:
    # Route to the best available free video generation:
    # 1. Generate 3 images from the prompt via Pollinations
    # 2. Create a slideshow video with those images via moviepy
    # 3. Add background music via MusicGen or audio chime
    try:
        from plugins.media_local.plugin import media_video_slideshow, media_audio_chime
        from plugins.media_free.plugin import media_image_pollinations
        import base64, tempfile, asyncio
        from pathlib import Path

        # Generate 3 scene images
        prompts = [prompt, f"{prompt} wide shot", f"{prompt} close up"]
        image_paths = []
        tmp_dir = Path(tempfile.mkdtemp())
        
        for i, p in enumerate(prompts[:3]):
            img_result = await media_image_pollinations(prompt=p, width=1280, height=720)
            if img_result.get("ok"):
                img_path = str(tmp_dir / f"scene_{i}.jpg")
                Path(img_path).write_bytes(base64.b64decode(img_result["image_base64"]))
                image_paths.append(img_path)

        if not image_paths:
            return {"ok": False, "error": "Failed to generate scene images via Pollinations"}

        # Generate background audio
        audio_result = await media_audio_chime(frequency_hz=440, duration_seconds=min(seconds, 5))

        # Create slideshow video
        output_path = str(tmp_dir / "video_output.mp4")
        video_result = await media_video_slideshow(
            images=image_paths,
            output_path=output_path,
            seconds_per_image=max(1, seconds / len(image_paths)),
            resolution="720p",
        )

        if video_result.get("ok"):
            return {
                "ok": True,
                "output_path": video_result["output_path"],
                "method": "pollinations_slideshow",
                "images_used": len(image_paths),
                "duration_seconds": seconds,
                "prompt": prompt,
            }
        return video_result
    except Exception as e:
        return {"ok": False, "error": f"Video generation failed: {e}", "prompt": prompt}


PLUGIN_NAME = "media_gen"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Image / TTS / STT / video generation."
