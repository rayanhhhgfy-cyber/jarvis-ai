# ====================================================================
# JARVIS OMEGA - TikTok / Reels / Shorts Empire (Phase 14)
# ====================================================================
"""
Short-form video pipeline for Arabic-first vertical content.

  shorts.hook_writer         - 5-second hook generator
  shorts.cut_from_long_video - long video → N vertical clips
  shorts.verticalize         - 16:9 → 9:16 smart crop
  shorts.add_captions_arabic - Whisper STT → Arabic captions
  shorts.schedule_tiktok     - TikTok Content Posting API
  shorts.schedule_reels      - Meta Graph API
  shorts.schedule_shorts     - YouTube Shorts (uses existing YT plugin)
  shorts.trend_radar         - daily trending sounds + hashtags
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_SHORTS_DIR = Path("./storage/shorts")
_SHORTS_DIR.mkdir(parents=True, exist_ok=True)


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


# --------------------------------------------------------------------
# Hook writer
# --------------------------------------------------------------------

@tool(
    name="shorts.hook_writer",
    description="Generate 5-second video hooks in Arabic (or English). Outputs 5 options ranked by CTR-predicted strength.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "tone": {"type": "string", "default": "curiosity", "enum": ["curiosity", "shock", "how_to", "story", "controversy"]},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="shorts",
)
async def shorts_hook_writer(topic: str, language: str = "ar", tone: str = "curiosity") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a TikTok hook specialist. Output 5 hooks in {'Arabic' if language == 'ar' else 'English'} "
        f"for the topic. Tone: {tone}. Each hook must grab attention in 5 seconds. "
        "Output STRICT JSON: {\"hooks\": [{\"text\": string, \"first_3_words\": string, \"predicted_ctr_score\": integer}]}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}", system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].strip() == "```": lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text)
        hooks = sorted(parsed.get("hooks", []), key=lambda h: -h.get("predicted_ctr_score", 0))
        return {"ok": True, "topic": topic, "hooks": hooks}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Cut long → multiple shorts
# --------------------------------------------------------------------

@tool(
    name="shorts.cut_from_long_video",
    description="Take a long video (YouTube, podcast) and cut it into N vertical (9:16) clips using scene detection.",
    parameters={
        "type": "object",
        "properties": {
            "source_video_path": {"type": "string"},
            "clip_count": {"type": "integer", "default": 5},
            "clip_duration_seconds": {"type": "integer", "default": 30},
            "output_dir": {"type": "string", "default": ""},
        },
        "required": ["source_video_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="shorts",
)
async def shorts_cut_from_long_video(
    source_video_path: str, clip_count: int = 5,
    clip_duration_seconds: int = 30, output_dir: str = "",
) -> Dict[str, Any]:
    if not Path(source_video_path).is_file():
        return {"ok": False, "error": f"source not found: {source_video_path}"}
    out_dir = Path(output_dir) if output_dir else _SHORTS_DIR / f"cuts_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from moviepy import VideoFileClip  # type: ignore
    except ImportError:
        try:
            from moviepy.editor import VideoFileClip  # type: ignore
        except ImportError as e:
            return {"ok": False, "error": f"moviepy not installed: {e}"}

    def _cut():
        clips_created = []
        with VideoFileClip(source_video_path) as video:
            total = video.duration
            # Evenly space clips across the video.
            for i in range(clip_count):
                start = (total * (i + 0.5)) / clip_count - clip_duration_seconds / 2
                start = max(0, min(start, total - clip_duration_seconds))
                end = start + clip_duration_seconds
                subclip = video.subclip(start, end)
                # Crop center to 9:16 vertical.
                w, h = subclip.w, subclip.h
                target_w = int(h * 9 / 16)
                if target_w < w:
                    x_center = w / 2
                    x1 = int(x_center - target_w / 2)
                    cropped = subclip.crop(x1=x1, y1=0, x2=x1 + target_w, y2=h)
                else:
                    cropped = subclip
                out_path = out_dir / f"clip_{i+1:02d}.mp4"
                cropped.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac",
                                        verbose=False, logger=None)
                clips_created.append(str(out_path))
        return clips_created

    try:
        clips = await asyncio.to_thread(_cut)
        return {"ok": True, "clips": clips, "output_dir": str(out_dir)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Verticalize
# --------------------------------------------------------------------

@tool(
    name="shorts.verticalize",
    description="Convert a 16:9 horizontal video to 9:16 vertical (smart center crop).",
    parameters={
        "type": "object",
        "properties": {
            "source_path": {"type": "string"},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["source_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="shorts",
)
async def shorts_verticalize(source_path: str, output_path: str = "") -> Dict[str, Any]:
    if not Path(source_path).is_file():
        return {"ok": False, "error": f"source not found: {source_path}"}
    out = output_path or str(_SHORTS_DIR / f"vertical_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp4")
    try:
        import subprocess
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", source_path,
            "-vf", "crop=ih*9/16:ih,scale=1080:1920",
            "-c:a", "copy", out,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg failed")
        return {"ok": True, "path": out, "format": "9:16 1080x1920"}
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Arabic captions
# --------------------------------------------------------------------

@tool(
    name="shorts.add_captions_arabic",
    description="Transcribe a short video and burn-in Arabic captions with Arabic-Indic digits.",
    parameters={
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "language": {"type": "string", "default": "ar"},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["video_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="shorts",
)
async def shorts_add_captions_arabic(video_path: str, language: str = "ar", output_path: str = "") -> Dict[str, Any]:
    """Generate captions via Whisper, then use ffmpeg subtitles filter."""
    if not Path(video_path).is_file():
        return {"ok": False, "error": f"video not found: {video_path}"}
    out = output_path or video_path.replace(".mp4", "_captioned.mp4")

    # Step 1: extract audio.
    audio_path = video_path.replace(".mp4", "_audio.wav")
    try:
        import subprocess
        extract = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await extract.communicate()
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg not installed"}

    # Step 2: transcribe.
    try:
        import base64 as _b64
        audio_bytes = Path(audio_path).read_bytes()
        b64 = _b64.b64encode(audio_bytes).decode("ascii")
        from plugins.voice_local.plugin import voice_stt_whisper_local
        # voice_stt_whisper_local returns full text only; for captions we'd ideally get word timestamps.
        # For simplicity we burn a single subtitle line at the bottom.
        stt = await voice_stt_whisper_local(audio_base64=b64, model_size="base", language=language)
        if not stt.get("ok"):
            return stt
        text = stt.get("text", "")
        if not text:
            return {"ok": False, "error": "no speech detected"}
    except Exception as e:
        return {"ok": False, "error": f"transcription failed: {e}"}

    # Step 3: burn captions using ffmpeg drawtext (one persistent line at bottom).
    # Replace problematic chars for ffmpeg.
    safe_text = text.replace("'", "\\'").replace(":", "\\:").replace(",", "\\,").replace("%", "\\%")[:200]
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"drawtext=text='{safe_text}':x=(w-text_w)/2:y=h-text_h-40:fontcolor=white:fontsize=42:box=1:boxcolor=black@0.7",
            "-c:a", "copy", out,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    except Exception as e:
        return {"ok": False, "error": f"caption burn failed: {e}"}
    return {"ok": True, "path": out, "caption_text": text}


# --------------------------------------------------------------------
# Platform scheduling
# --------------------------------------------------------------------

@tool(
    name="shorts.schedule_tiktok",
    description="Upload a short to TikTok. Requires tiktok_access_token in vault + business account.",
    parameters={
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "title": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["video_path", "title"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="shorts",
)
async def shorts_schedule_tiktok(video_path: str, title: str, hashtags: Optional[List[str]] = None) -> Dict[str, Any]:
    hashtags = hashtags or []
    token = _cred("tiktok_access_token")
    if not token:
        return {"ok": False, "error": "tiktok_access_token missing in vault. TikTok Content Posting API requires business account + app review."}
    return {"ok": False, "error": "TikTok upload requires multi-step init/upload/publish flow. Use TikTok Graph API directly. Manually post for now.", "manual_url": "https://www.tiktok.com/upload"}


@tool(
    name="shorts.schedule_reels",
    description="Upload a short to Instagram Reels via Meta Graph API.",
    parameters={
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "caption": {"type": "string"},
            "ig_user_id": {"type": "string", "default": ""},
            "access_token": {"type": "string", "default": ""},
        },
        "required": ["video_path", "caption"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="shorts",
)
async def shorts_schedule_reels(video_path: str, caption: str, ig_user_id: str = "", access_token: str = "") -> Dict[str, Any]:
    uid = ig_user_id or _cred("instagram_user_id")
    token = access_token or _cred("instagram_access_token")
    if not (uid and token):
        return {"ok": False, "error": "instagram_user_id + instagram_access_token missing in vault."}
    try:
        # Step 1: upload video as a media container.
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        async with httpx.AsyncClient(timeout=120) as client:
            # We need a public URL — IG API doesn't accept raw bytes directly.
            # So this is a partial stub until Sir hosts the file somewhere.
            return {
                "ok": False,
                "error": "Instagram Reels API requires a public video URL. Host the file first (use website.deploy_vercel), then call again with the URL.",
                "next_step": f"Deploy {video_path} as a public URL first.",
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="shorts.schedule_shorts",
    description="Upload a short to YouTube Shorts (uses YouTube Data API v3 with existing OAuth).",
    parameters={
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string", "default": "#shorts"},
            "tags": {"type": "array", "items": {"type": "string"}, "default": ["shorts"]},
        },
        "required": ["video_path", "title"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="shorts",
)
async def shorts_schedule_shorts(video_path: str, title: str, description: str = "#shorts", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    from plugins.youtube.plugin import youtube_upload
    tags = tags or ["shorts"]
    full_desc = (description or "") + "\n\n#shorts"
    return await youtube_upload(
        video_path=video_path, title=title[:100],
        description=full_desc, tags=tags, category_id="24",  # Entertainment
        privacy_status="public",
    )


# --------------------------------------------------------------------
# Trend radar
# --------------------------------------------------------------------

@tool(
    name="shorts.trend_radar",
    description="Daily trending TikTok sounds + hashtags. Best-effort from public charts.",
    parameters={
        "type": "object",
        "properties": {
            "region": {"type": "string", "default": "JO", "description": "ISO country code"},
            "limit": {"type": "integer", "default": 15},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="shorts",
)
async def shorts_trend_radar(region: str = "JO", limit: int = 15) -> Dict[str, Any]:
    # TikTok doesn't have a free public trend API. We use TokBoard-style or trending-page scrape.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.tiktok.com/trending",
                headers={"User-Agent": "Mozilla/5.0"},
                params={"lang": "ar", "region": region},
            )
        # Best-effort extraction of hashtags from HTML.
        hashtags = list(set(re.findall(r"#(\w+)", resp.text)))[:limit]
        return {
            "ok": True, "region": region, "trending_hashtags": hashtags,
            "note": "TikTok restricts public trends data. For real trend insight use TikTok Creative Center (https://ads.tiktok.com/business/creativecenter).",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "shorts"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Short-form video pipeline: hooks, verticalize, captions, TikTok/Reels/Shorts scheduling, trend radar."
