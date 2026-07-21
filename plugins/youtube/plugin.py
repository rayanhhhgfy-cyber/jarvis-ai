# ====================================================================
# JARVIS OMEGA - YouTube Channel Automation Plugin (Phase 13)
# ====================================================================
"""
End-to-end YouTube pipeline for an autonomous Arabic channel.

  youtube.script_write        - LLM writes a script (Arabic)
  youtube.thumbnail_generate  - Pollinations image + Pillow Arabic overlay
  youtube.voiceover           - edge-tts Arabic narration
  youtube.video_assemble      - moviepy: voiceover + B-roll + captions → MP4
  youtube.upload              - YouTube Data API v3 (OAuth)
  youtube.seo_optimize        - title/description/tags in Arabic
  youtube.analytics           - YouTube Analytics API (views, revenue)
  youtube.competitor_track    - monitor competitor channels
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import random
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("youtube")

_YT_DIR = Path("./storage/youtube")
_YT_DIR.mkdir(parents=True, exist_ok=True)


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


# --------------------------------------------------------------------
# Script writing
# --------------------------------------------------------------------

@tool(
    name="youtube.script_write",
    description="Generate a YouTube video script (Arabic by default). Returns structured JSON with scenes.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "length_minutes": {"type": "integer", "default": 5},
            "style": {"type": "string", "default": "informative", "description": "informative | entertaining | educational | dramatic"},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="youtube",
)
async def youtube_script_write(
    topic: str, language: str = "ar", length_minutes: int = 5, style: str = "informative",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a senior YouTube scriptwriter. Output STRICT JSON in {'Arabic' if language == 'ar' else 'English'}: "
        "{\"title\": string, \"hook\": string, \"scenes\": [{\"narration\": string, \"b_roll_prompt\": string, \"duration_seconds\": integer}], \"cta\": string}. "
        f"Total runtime ~{length_minutes} min. Style: {style}. Hook must grab attention in 5 seconds."
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}",
            system_instructions=sys_prompt,
            inject_memory=False,
        )
        # Salvage JSON.
        cleaned = reply.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        parsed = json.loads(cleaned[start:i + 1])
                        break
        # Persist.
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = _YT_DIR / f"script_{stamp}.json"
        path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "ok": True, "topic": topic, "language": language,
            "title": parsed.get("title"), "hook": parsed.get("hook"),
            "scene_count": len(parsed.get("scenes", [])),
            "script_path": str(path),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Thumbnail generation
# --------------------------------------------------------------------

@tool(
    name="youtube.thumbnail_generate",
    description="Generate a 1280x720 YouTube thumbnail: Pollinations background + Arabic text overlay.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title text to overlay (max ~30 chars)."},
            "image_prompt": {"type": "string", "description": "What the background image should depict."},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["title", "image_prompt"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="youtube",
)
async def youtube_thumbnail_generate(
    title: str, image_prompt: str, language: str = "ar",
    output_path: str = "",
) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": f"Pillow not installed: {e}"}
    # Fetch background from Pollinations.
    bg_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(image_prompt, safe='')}?width=1280&height=720&nologo=true"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(bg_url)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"Pollinations error: {resp.status_code}"}
        bg = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        return {"ok": False, "error": f"image fetch failed: {e}"}

    draw = ImageDraw.Draw(bg)
    # Find an Arabic-capable font.
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    font = None
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 72)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Draw text on the left third with shadow + outline.
    text = title
    # Background bar.
    bar_w = int(bg.width * 0.7)
    bar_h = int(bg.height * 0.4)
    bar_x = int(bg.width * 0.05)
    bar_y = int(bg.height * 0.55)
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=(0, 0, 0, 200))
    # Multi-line wrap.
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= 25:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    text_y = bar_y + 20
    for ln in lines[:4]:
        # Shadow.
        draw.text((bar_x + 22, text_y + 3), ln, font=font, fill="black")
        draw.text((bar_x + 25, text_y), ln, font=font, fill="yellow")
        text_y += 75

    out = output_path or str(_YT_DIR / f"thumbnail_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg")
    bg.save(out, "JPEG", quality=92)
    return {"ok": True, "path": out, "title": title, "language": language}


# --------------------------------------------------------------------
# Voiceover via edge-tts (reuse existing plugin)
# --------------------------------------------------------------------

@tool(
    name="youtube.voiceover",
    description="Generate an Arabic MP3 voiceover from a script. Default voice: ar-JZ-AyoubNeural.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Narration text."},
            "voice": {"type": "string", "default": "ar-JZ-AyoubNeural", "description": "Try: ar-JZ-AyoubNeural, ar-SA-HamedNeural, ar-EG-SalmaNeural"},
            "output_path": {"type": "string", "default": ""},
            "rate": {"type": "string", "default": "+0%"},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="youtube",
)
async def youtube_voiceover(text: str, voice: str = "ar-JZ-AyoubNeural", output_path: str = "", rate: str = "+0%") -> Dict[str, Any]:
    from plugins.voice_local.plugin import voice_tts_edge
    result = await voice_tts_edge(text=text, voice=voice, rate=rate)
    if not result.get("ok"):
        return result
    # Decode to file if output_path provided.
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(base64.b64decode(result["audio_base64"]))
        return {"ok": True, "path": output_path, "format": "mp3", "bytes": result["bytes"], "voice": voice}
    return result


# --------------------------------------------------------------------
# Video assembly
# --------------------------------------------------------------------

@tool(
    name="youtube.video_assemble",
    description="Assemble an MP4 from a voiceover + background images + Arabic captions (SRT).",
    parameters={
        "type": "object",
        "properties": {
            "voiceover_path": {"type": "string"},
            "image_paths": {"type": "array", "items": {"type": "string"}, "default": [], "description": "Background images; cycles through video length."},
            "captions_srt_path": {"type": "string", "default": "", "description": "Optional WebVTT/SRT captions file."},
            "output_path": {"type": "string", "default": ""},
            "resolution": {"type": "string", "enum": ["720p", "1080p"], "default": "1080p"},
        },
        "required": ["voiceover_path"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="youtube",
)
async def youtube_video_assemble(
    voiceover_path: str, image_paths: Optional[List[str]] = None,
    captions_srt_path: str = "", output_path: str = "",
    resolution: str = "1080p",
) -> Dict[str, Any]:
    image_paths = image_paths or []
    try:
        from moviepy import ImageClip, AudioFileClip, concatenate_videoclips  # type: ignore
    except ImportError:
        try:
            from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips  # type: ignore
        except ImportError as e:
            return {"ok": False, "error": f"moviepy not installed: {e}"}

    res = (1920, 1080) if resolution == "1080p" else (1280, 720)

    out_path = output_path or str(_YT_DIR / f"video_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp4")

    def _build():
        audio = AudioFileClip(voiceover_path)
        duration = audio.duration
        # Build a sequence of image clips to fill the audio duration.
        if image_paths:
            n_segments = max(1, int(math.ceil(duration / 5)))  # 5s per image
            clips = []
            for i in range(n_segments):
                img = image_paths[i % len(image_paths)]
                clip = ImageClip(img).with_duration(min(5, duration - i * 5)).resized(res)
                clips.append(clip)
            video = concatenate_videoclips(clips, method="compose").with_audio(audio)
        else:
            # Black background.
            from PIL import Image
            with io.BytesIO() as buf:
                Image.new("RGB", res, (0, 0, 0)).save(buf, "PNG")
                black = buf.getvalue()
            video = ImageClip(io.BytesIO(black)).with_duration(duration).with_audio(audio)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac",
                              verbose=False, logger=None)
        return Path(out_path).stat().st_size

    try:
        size = await asyncio.to_thread(_build)
        return {
            "ok": True, "output_path": out_path, "size_bytes": size,
            "audio_source": voiceover_path, "resolution": resolution,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Upload via YouTube Data API v3
# --------------------------------------------------------------------

@tool(
    name="youtube.upload",
    description="Upload a video to YouTube. Requires one-time OAuth setup (youtube_oauth_json in vault).",
    parameters={
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string", "default": ""},
            "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            "category_id": {"type": "string", "default": "22", "description": "22=People & Blogs, 27=Education, 24=Entertainment"},
            "privacy_status": {"type": "string", "enum": ["public", "unlisted", "private"], "default": "private"},
        },
        "required": ["video_path", "title"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="youtube",
)
async def youtube_upload(
    video_path: str, title: str, description: str = "",
    tags: Optional[List[str]] = None, category_id: str = "22",
    privacy_status: str = "private",
) -> Dict[str, Any]:
    tags = tags or []
    oauth_path = _cred("youtube_oauth_json")
    if not oauth_path:
        return {
            "ok": False,
            "error": "youtube_oauth_json not in vault. One-time setup: create a GCP project, enable YouTube Data API v3, generate OAuth client_secret.json.",
        }
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaFileUpload  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": f"google libraries missing: {e}"}

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]

    def _do():
        # Load the OAuth client secret JSON (file path or inline JSON).
        client_config_path = oauth_path
        if not Path(oauth_path).exists():
            # Maybe it's the inline JSON string — write to a temp file.
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(oauth_path)
                client_config_path = tf.name
        flow = InstalledAppFlow.from_client_secrets_file(client_config_path, scopes)
        creds = flow.run_local_server(port=0)
        youtube = build("youtube", "v3", credentials=creds)
        request_body = {
            "snippet": {
                "title": title[:100],  # YT enforces 100-char cap
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": category_id,
            },
            "status": {"privacyStatus": privacy_status},
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
        request = youtube.videos().insert(part=",".join(request_body.keys()), body=request_body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
        return response

    try:
        result = await asyncio.to_thread(_do)
        # Persist.
        business_db.execute(
            """INSERT INTO youtube_uploads (video_id, title, description, tags, video_path, status, uploaded_at, created_at)
               VALUES (?, ?, ?, ?, ?, 'uploaded', ?, ?)""",
            (result.get("id"), title, description, json.dumps(tags), video_path,
             datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        return {
            "ok": True, "video_id": result.get("id"),
            "url": f"https://www.youtube.com/watch?v={result.get('id')}",
            "title": title, "privacy_status": privacy_status,
        }
    except Exception as e:
        business_db.execute(
            """INSERT INTO youtube_uploads (title, video_path, status, error, created_at)
               VALUES (?, ?, 'failed', ?, ?)""",
            (title, video_path, str(e)[:500], datetime.utcnow().isoformat()),
        )
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# SEO optimize
# --------------------------------------------------------------------

@tool(
    name="youtube.seo_optimize",
    description="Optimize title/description/tags for YouTube SEO in Arabic (or English).",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["topic"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="youtube",
)
async def youtube_seo_optimize(topic: str, language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a YouTube SEO expert for the MENA region. Output STRICT JSON in {'Arabic' if language == 'ar' else 'English'}: "
        "{\"title\": string (max 70 chars, high CTR), \"description\": string (min 200 chars, includes keyword + hashtags), "
        "\"tags\": [string, ...] (15-20 tags, mix of broad + specific), \"hashtag_list\": [string, ...] (3 hashtags, no #)}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Topic: {topic}",
            system_instructions=sys_prompt,
            inject_memory=False,
        )
        text = reply.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text)
        return {"ok": True, "topic": topic, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------

@tool(
    name="youtube.analytics",
    description="Fetch YouTube Analytics (views, watch time, revenue) for the authenticated channel.",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "default": "", "description": "YYYY-MM-DD. Default: 28 days ago."},
            "end_date": {"type": "string", "default": "", "description": "YYYY-MM-DD. Default: today."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="youtube",
)
async def youtube_analytics(start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    oauth_path = _cred("youtube_oauth_json")
    if not oauth_path:
        return {"ok": False, "error": "youtube_oauth_json not in vault"}
    try:
        from google.oauth2.credentials import Credentials  # type: ignore  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": str(e)}
    end = end_date or datetime.utcnow().strftime("%Y-%m-%d")
    start = start_date or (datetime.utcnow() - timedelta(days=28)).strftime("%Y-%m-%d")
    scopes = ["https://www.googleapis.com/auth/youtube.readonly"]

    def _do():
        client_config_path = oauth_path
        if not Path(oauth_path).exists():
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(oauth_path)
                client_config_path = tf.name
        flow = InstalledAppFlow.from_client_secrets_file(client_config_path, scopes)
        creds = flow.run_local_server(port=0)
        youtube = build("youtubeAnalytics", "v2", credentials=creds)
        resp = youtube.reports().query(
            ids="channel==MINE",
            startDate=start, endDate=end,
            metrics="views,estimatedMinutesWatched,estimatedRevenue,subscribersGained,likes,comments",
        ).execute()
        return resp

    try:
        rows = await asyncio.to_thread(_do)
        cols = [c["name"] for c in rows.get("columnHeaders", [])]
        vals = rows.get("rows", [[]])[0]
        return {"ok": True, "start_date": start, "end_date": end, "data": dict(zip(cols, vals))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Competitor tracking
# --------------------------------------------------------------------

@tool(
    name="youtube.competitor_track",
    description="Pull stats for a competitor's latest videos (no auth required — public scrape).",
    parameters={
        "type": "object",
        "properties": {
            "channel_url": {"type": "string", "description": "e.g. https://www.youtube.com/@MrBeast"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["channel_url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="youtube",
)
async def youtube_competitor_track(channel_url: str, limit: int = 10) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(channel_url + "/videos", headers={"User-Agent": "Mozilla/5.0"})
        # Extract video IDs from page HTML.
        ids = re.findall(r'"videoId":"([\w\-]{11})"', resp.text)
        unique = list(dict.fromkeys(ids))[:limit]
        videos = []
        for vid in unique:
            videos.append({"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"})
        return {"ok": True, "channel": channel_url, "count": len(videos), "videos": videos}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "youtube"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "YouTube channel automation: scripts (Arabic), thumbnails, voiceover, video assembly, upload, SEO, analytics."
