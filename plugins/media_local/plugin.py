# ====================================================================
# JARVIS OMEGA - Free Local Media Plugin (moviepy + chimes + MusicGen)
# ====================================================================
"""
Phase 10 plugin: free media generation that doesn't need any paid API.

  * ``media.video_slideshow`` - assemble an image sequence + audio track
    into an MP4 via moviepy + ffmpeg.
  * ``media.audio_chime``     - synthesize a short sine-wave chime via
    numpy + soundfile (no ffmpeg needed for WAV output).
  * ``media.musicgen_local``  - generate a short music clip locally via
    Meta's MusicGen (transformers + scipy). Big download on first use
    (~few GB) but free; CPU is slow but works.

All tools degrade gracefully if optional deps are missing.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Slideshow (moviepy + ffmpeg)
# --------------------------------------------------------------------

@tool(
    name="media.video_slideshow",
    description="Create an MP4 slideshow from a list of image file paths. Optional audio track.",
    parameters={
        "type": "object",
        "properties": {
            "images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of image file paths.",
            },
            "output_path": {"type": "string", "description": "Output MP4 path."},
            "seconds_per_image": {"type": "number", "default": 3.0},
            "audio_path": {"type": "string", "default": "", "description": "Optional background audio file."},
            "resolution": {"type": "string", "enum": ["480p", "720p", "1080p"], "default": "720p"},
        },
        "required": ["images", "output_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_video_slideshow(
    images: List[str], output_path: str,
    seconds_per_image: float = 3.0, audio_path: str = "",
    resolution: str = "720p",
) -> Dict[str, Any]:
    if not images:
        return {"ok": False, "error": "no images provided"}
    try:
        from moviepy import ImageClip, AudioFileClip, concatenate_videoclips  # type: ignore
    except ImportError:
        try:
            from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips  # type: ignore
        except ImportError:
            return {"ok": False, "error": "moviepy not installed — add `moviepy` to requirements.txt and ffmpeg to PATH"}

    res_map = {"480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080)}
    w, h = res_map.get(resolution, (1280, 720))

    def _build():
        clips = []
        for img in images:
            try:
                clip = ImageClip(img).with_duration(seconds_per_image).resized((w, h))
                clips.append(clip)
            except Exception as e:
                raise RuntimeError(f"failed to load image {img}: {e}")
        video = concatenate_videoclips(clips, method="compose")
        if audio_path and Path(audio_path).is_file():
            try:
                audio = AudioFileClip(audio_path)
                # Loop / trim audio to fit video duration.
                if audio.duration < video.duration:
                    # Repeat by concatenation.
                    loops = int(math.ceil(video.duration / audio.duration))
                    audio = concatenate_videoclips([audio] * loops).with_duration(video.duration)
                else:
                    audio = audio.with_duration(video.duration)
                video = video.with_audio(audio)
            except Exception:
                pass
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac",
                              verbose=False, logger=None)
        return {"size_bytes": Path(output_path).stat().st_size}

    try:
        result = await asyncio.to_thread(_build)
        return {
            "ok": True,
            "output_path": output_path,
            "images": len(images),
            "seconds_per_image": seconds_per_image,
            "resolution": resolution,
            **result,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Audio chime (numpy + soundfile)
# --------------------------------------------------------------------

@tool(
    name="media.audio_chime",
    description="Generate a short sine-wave chime. Returns base64 WAV.",
    parameters={
        "type": "object",
        "properties": {
            "frequency_hz": {"type": "number", "default": 880.0},
            "duration_seconds": {"type": "number", "default": 0.5},
            "sample_rate": {"type": "integer", "default": 22050},
            "fade_ms": {"type": "integer", "default": 20},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_audio_chime(
    frequency_hz: float = 880.0, duration_seconds: float = 0.5,
    sample_rate: int = 22050, fade_ms: int = 20,
) -> Dict[str, Any]:
    try:
        import numpy as np
        import soundfile as sf  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": f"required lib missing: {e}"}

    def _gen():
        n = int(sample_rate * duration_seconds)
        t = np.linspace(0, duration_seconds, n, endpoint=False, dtype=np.float32)
        wave = 0.5 * np.sin(2 * math.pi * frequency_hz * t)
        # Linear fade in/out to avoid clicks.
        fade = int(sample_rate * fade_ms / 1000)
        if fade > 0 and 2 * fade < n:
            ramp = np.linspace(0, 1, fade, dtype=np.float32)
            wave[:fade] *= ramp
            wave[-fade:] *= ramp[::-1]
        buf = io.BytesIO()
        sf.write(buf, wave, sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    audio_bytes = await asyncio.to_thread(_gen)
    return {
        "ok": True,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "format": "wav",
        "bytes": len(audio_bytes),
        "frequency_hz": frequency_hz,
        "duration_seconds": duration_seconds,
    }


# --------------------------------------------------------------------
# MusicGen local (transformers)
# --------------------------------------------------------------------

_musicgen_model = None


def _get_musicgen_model(model_name: str = "facebook/musicgen-small"):
    """Lazy-load the MusicGen model. Big download on first call (~few GB)."""
    global _musicgen_model
    if _musicgen_model is not None and _musicgen_model[0] == model_name:
        return _musicgen_model[1]
    try:
        from transformers import AutoProcessor, MusicgenForConditionalGeneration  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "transformers + torch not installed — add `transformers torch scipy` to requirements.txt"
        ) from e
    processor = AutoProcessor.from_pretrained(model_name)
    model = MusicgenForConditionalGeneration.from_pretrained(model_name)
    _musicgen_model = (model_name, (processor, model))
    return _musicgen_model[1]


@tool(
    name="media.musicgen_local",
    description="Generate a short music clip locally via Meta's MusicGen. Big download on first use (~1.5 GB for 'small' model). Returns base64 WAV.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Description of the music (e.g. 'upbeat electronic with driving bass')."},
            "seconds": {"type": "number", "default": 10.0, "description": "Duration (max ~30 for CPU sanity)."},
            "model": {"type": "string", "default": "facebook/musicgen-small", "enum": ["facebook/musicgen-small", "facebook/musicgen-medium", "facebook/musicgen-melody"]},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_musicgen_local(prompt: str, seconds: float = 10.0, model: str = "facebook/musicgen-small") -> Dict[str, Any]:
    seconds = max(1.0, min(30.0, seconds))
    try:
        processor, mg_model = _get_musicgen_model(model)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    try:
        import torch  # type: ignore
        import scipy.io.wavfile  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": f"torch/scipy missing: {e}"}

    def _generate():
        inputs = processor(text=[prompt], padding=True, return_tensors="pt")
        # MusicGen produces ~50 tokens per second of audio.
        max_new_tokens = int(seconds * 50)
        with torch.no_grad():
            audio_values = mg_model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True)
        sampling_rate = mg_model.config.audio_encoder.sampling_rate
        # Trim to requested duration.
        target_samples = int(seconds * sampling_rate)
        audio = audio_values[0, 0, :target_samples].numpy()
        # Write to a buffer.
        buf = io.BytesIO()
        scipy.io.wavfile.write(buf, rate=sampling_rate, data=audio)
        return buf.getvalue(), sampling_rate

    try:
        audio_bytes, sr = await asyncio.to_thread(_generate)
        return {
            "ok": True,
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "format": "wav",
            "bytes": len(audio_bytes),
            "sampling_rate": sr,
            "prompt": prompt,
            "model": model,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "media_local"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free local media generation: slideshow (moviepy), audio chimes, MusicGen via transformers."
