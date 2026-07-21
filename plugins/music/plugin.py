# ====================================================================
# JARVIS OMEGA - AI Music Albums (Phase 14)
# ====================================================================
"""
Generate complete music albums and distribute them.

  music.album_concept         - LLM writes concept + 10 song themes
  music.lyrics_write          - Arabic + English lyrics
  music.generate_song_suno     - Suno API ($10/mo for ~500 songs)
  music.generate_song_musicgen - free fallback: MusicGen local
  music.album_art             - Pollinations cover art
  music.distribute_distrokid  - DistroKid API ($20/yr unlimited)
  music.royalty_track         - per-stream revenue tracking
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_MUSIC_DIR = Path("./storage/music")
_MUSIC_DIR.mkdir(parents=True, exist_ok=True)


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


@tool(
    name="music.album_concept",
    description="Generate an album concept: 10 song themes around a unifying idea.",
    parameters={
        "type": "object",
        "properties": {
            "genre": {"type": "string", "default": "ambient electronic"},
            "mood": {"type": "string", "default": "reflective morning"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
            "song_count": {"type": "integer", "default": 8},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="music",
)
async def music_album_concept(
    genre: str = "ambient electronic", mood: str = "reflective morning",
    language: str = "ar", song_count: int = 8,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a music producer. Output STRICT JSON in {'Arabic' if language == 'ar' else 'English'}: "
        "{\"album_title\": string, \"concept\": string, \"songs\": [{\"title\": string, \"theme\": string, \"tempo_bpm\": integer, \"duration_seconds\": integer}]}"
        f"Genre: {genre}, Mood: {mood}, Song count: {song_count}."
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Generate album concept.",
            system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        return {"ok": True, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="music.lyrics_write",
    description="Write song lyrics for a given theme. Bilingual Arabic + English.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "theme": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en", "both"]},
            "verse_count": {"type": "integer", "default": 3},
        },
        "required": ["title", "theme"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="music",
)
async def music_lyrics_write(title: str, theme: str, language: str = "ar", verse_count: int = 3) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a songwriter. Write {verse_count} verses + 1 chorus in "
        f"{'Arabic' if language == 'ar' else 'English' if language == 'en' else 'both Arabic and English'}. "
        f"Theme: {theme}. Output STRICT JSON: "
        "{\"verses\": [string], \"chorus\": string, \"bridge\": string}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Title: {title}", system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        return {"ok": True, "title": title, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="music.generate_song_suno",
    description="Generate a song via Suno AI. Requires suno_api_key in vault. ~$10/month for 500 songs.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Description of the song (style, mood, instruments)."},
            "title": {"type": "string"},
            "lyrics": {"type": "string", "default": "", "description": "Optional custom lyrics."},
            "duration_seconds": {"type": "integer", "default": 60},
        },
        "required": ["prompt", "title"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="music",
)
async def music_generate_song_suno(prompt: str, title: str, lyrics: str = "", duration_seconds: int = 60) -> Dict[str, Any]:
    key = _cred("suno_api_key")
    if not key:
        return {"ok": False, "error": "suno_api_key not in vault. Sign up at https://suno.com (~$10/mo for ~500 songs)."}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # Suno has unofficial APIs — we use the most common pattern.
            resp = await client.post(
                "https://studio-api.suno.ai/api/generate/v2/",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "gpt_description_prompt": prompt,
                    "make_instrumental": not lyrics,
                    "mv": "chirp-v3-0",
                },
            )
        if resp.status_code >= 400:
            return {"ok": False, "error": f"Suno error {resp.status_code}: {resp.text[:300]}", "hint": "Suno doesn't have an official public API — use the unofficial `suno-api` PyPI package or browser automation."}
        return {"ok": True, "title": title, "response": resp.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="music.generate_song_musicgen",
    description="Generate a song locally via Meta's MusicGen. Free but CPU-slow (~3-5min per 10s on CPU).",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "duration_seconds": {"type": "number", "default": 15},
            "model": {"type": "string", "default": "facebook/musicgen-small", "enum": ["facebook/musicgen-small", "facebook/musicgen-medium", "facebook/musicgen-melody"]},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="music",
)
async def music_generate_song_musicgen(prompt: str, duration_seconds: float = 15, model: str = "facebook/musicgen-small") -> Dict[str, Any]:
    from plugins.media_local.plugin import media_musicgen_local
    return await media_musicgen_local(prompt=prompt, seconds=duration_seconds, model=model)


@tool(
    name="music.album_art",
    description="Generate album cover art via Pollinations.",
    parameters={
        "type": "object",
        "properties": {
            "album_title": {"type": "string"},
            "visual_prompt": {"type": "string"},
            "output_path": {"type": "string", "default": ""},
        },
        "required": ["album_title", "visual_prompt"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="music",
)
async def music_album_art(album_title: str, visual_prompt: str, output_path: str = "") -> Dict[str, Any]:
    from plugins.media_free.plugin import media_image_pollinations
    result = await media_image_pollinations(
        prompt=f"{visual_prompt}, square album cover art, no text",
        width=1024, height=1024,
    )
    if not result.get("ok"):
        return result
    out = output_path or str(_MUSIC_DIR / f"cover_{album_title.lower().replace(' ', '_')}.png")
    Path(out).write_bytes(base64.b64decode(result["image_base64"]))
    return {"ok": True, "path": out, "album": album_title}


@tool(
    name="music.distribute_distrokid",
    description="Upload a song to DistroKid for Spotify/Apple Music distribution. Requires distrokid_email + password in vault.",
    parameters={
        "type": "object",
        "properties": {
            "audio_path": {"type": "string"},
            "title": {"type": "string"},
            "artist_name": {"type": "string"},
            "isrc": {"type": "string", "default": "", "description": "Optional ISRC code. Empty = DistroKid assigns."},
        },
        "required": ["audio_path", "title", "artist_name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="music",
)
async def music_distribute_distrokid(audio_path: str, title: str, artist_name: str, isrc: str = "") -> Dict[str, Any]:
    # DistroKid doesn't have a public upload API. We provide a direct upload link.
    return {
        "ok": False,
        "error": "DistroKid has no public upload API.",
        "manual_url": "https://distrokid.com/new",
        "title": title, "artist": artist_name,
        "instructions": "Manually upload via the URL above. Requires DistroKid subscription ($20/yr).",
        "alt": "Use RouteNote (free distribution) at https://routenote.com",
    }


@tool(
    name="music.royalty_track",
    description="Estimate streaming royalties based on play count.",
    parameters={
        "type": "object",
        "properties": {
            "play_count_spotify": {"type": "integer", "default": 0},
            "play_count_apple": {"type": "integer", "default": 0},
            "play_count_youtube": {"type": "integer", "default": 0},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="music",
)
async def music_royalty_track(play_count_spotify: int = 0, play_count_apple: int = 0, play_count_youtube: int = 0) -> Dict[str, Any]:
    # Approximate per-stream rates (USD).
    spotify_rate = 0.0035
    apple_rate = 0.007
    youtube_rate = 0.001
    spotify_rev = play_count_spotify * spotify_rate
    apple_rev = play_count_apple * apple_rate
    youtube_rev = play_count_youtube * youtube_rate
    total = spotify_rev + apple_rev + youtube_rev
    return {
        "ok": True,
        "spotify_plays": play_count_spotify, "spotify_revenue_usd": round(spotify_rev, 2),
        "apple_plays": play_count_apple, "apple_revenue_usd": round(apple_rev, 2),
        "youtube_plays": play_count_youtube, "youtube_revenue_usd": round(youtube_rev, 2),
        "total_revenue_usd": round(total, 2),
        "estimated_jod": round(total * 0.71, 2),
        "note": "Approximate. Actual rates vary by listener country + subscription tier.",
    }


PLUGIN_NAME = "music"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "AI music albums: concept, lyrics, Suno/MusicGen generation, cover art, royalty tracking."
