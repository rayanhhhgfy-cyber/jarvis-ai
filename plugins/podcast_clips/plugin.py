# Phase 18: Podcast Clip Generator (REAL)
from __future__ import annotations
import asyncio
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="podcast_clips.find_best", description="Cut a long podcast audio into 60-second clips at regular intervals.", parameters={"type":"object","properties":{"audio_path":{"type":"string"},"clip_count":{"type":"integer","default":5},"clip_duration_seconds":{"type":"integer","default":60}},"required":["audio_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="podcast_clips")
async def find_best(audio_path: str, clip_count: int = 5, clip_duration_seconds: int = 60) -> Dict[str, Any]:
    try:
        from moviepy import AudioFileClip  # type: ignore
    except ImportError:
        try:
            from moviepy.editor import AudioFileClip  # type: ignore
        except ImportError:
            return {"ok": False, "error": "moviepy not installed"}
    from pathlib import Path
    out_dir = Path("./storage/podcast_clips"); out_dir.mkdir(parents=True, exist_ok=True)
    def _cut():
        audio = AudioFileClip(audio_path)
        total = audio.duration
        clips = []
        for i in range(clip_count):
            start = (total * (i + 0.5)) / clip_count - clip_duration_seconds / 2
            start = max(0, min(start, total - clip_duration_seconds))
            clip = audio.subclip(start, start + clip_duration_seconds)
            path = str(out_dir / f"clip_{i+1:02d}.mp3")
            clip.write_audiofile(path, verbose=False, logger=None)
            clips.append(path)
        audio.close()
        return clips
    try:
        clips = await asyncio.to_thread(_cut)
        return {"ok": True, "clips": clips, "clip_count": len(clips)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
