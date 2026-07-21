# ====================================================================
# JARVIS OMEGA - Free Podcast Plugin (RSS + transcribe)
# ====================================================================
"""
Phase 10 plugin: subscribe to podcasts and transcribe episodes.

  * ``podcast.list_episodes`` - parse a podcast RSS feed and list episodes.
  * ``podcast.download``      - download an episode MP3 to local disk.
  * ``podcast.transcribe``    - download + transcribe an episode using
                                the existing voice_local Whisper tool.

Uses ``feedparser`` and ``httpx``. Both are free / no API keys.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_UA = "JARVIS-OMEGA/1.0 (+podcast-tool)"
_PODCAST_DIR = Path("./storage/podcasts")


@tool(
    name="podcast.list_episodes",
    description="Parse a podcast RSS feed and return the most recent episodes.",
    parameters={
        "type": "object",
        "properties": {
            "feed_url": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["feed_url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="podcast",
)
async def podcast_list_episodes(feed_url: str, limit: int = 10) -> Dict[str, Any]:
    try:
        import feedparser  # type: ignore
    except ImportError:
        return {"ok": False, "error": "feedparser not installed"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": _UA})
        parsed = feedparser.parse(resp.content)
        episodes = []
        for e in parsed.entries[:limit]:
            audio_url = ""
            duration = ""
            for link in e.get("links", []):
                if "audio" in link.get("type", ""):
                    audio_url = link.get("href", "")
                    break
            if not audio_url and e.get("enclosures"):
                audio_url = e.enclosures[0].get("href", "")
                duration = e.enclosures[0].get("length", "")
            episodes.append({
                "title": e.get("title", ""),
                "published": e.get("published", ""),
                "duration": duration,
                "audio_url": audio_url,
                "summary": (e.get("summary", "") or "")[:500],
            })
        return {
            "ok": True,
            "feed_title": parsed.feed.get("title", ""),
            "count": len(episodes),
            "episodes": episodes,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="podcast.download",
    description="Download a podcast episode MP3 to local storage. Returns the local path.",
    parameters={
        "type": "object",
        "properties": {
            "audio_url": {"type": "string"},
            "filename": {"type": "string", "description": "Optional filename (without extension)."},
            "max_bytes": {"type": "integer", "default": 100_000_000, "description": "Hard cap (~100 MB)."},
        },
        "required": ["audio_url"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="podcast",
)
async def podcast_download(audio_url: str, filename: str = "", max_bytes: int = 100_000_000) -> Dict[str, Any]:
    _PODCAST_DIR.mkdir(parents=True, exist_ok=True)
    name = filename or audio_url.rsplit("/", 1)[-1].split("?")[0] or "episode.mp3"
    if not name.endswith((".mp3", ".m4a", ".aac", ".wav", ".ogg")):
        name = f"{name}.mp3"
    dest = _PODCAST_DIR / name
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", audio_url, headers={"User-Agent": _UA}) as stream:
                if stream.status_code >= 400:
                    return {"ok": False, "status": stream.status_code, "error": "download failed"}
                written = 0
                with open(dest, "wb") as fh:
                    async for chunk in stream.aiter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            fh.close()
                            dest.unlink(missing_ok=True)
                            return {"ok": False, "error": f"episode exceeds max_bytes={max_bytes}"}
                        fh.write(chunk)
        return {
            "ok": True,
            "url": audio_url,
            "file": str(dest),
            "bytes": written,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="podcast.transcribe",
    description="Download an episode and transcribe it with the local Whisper tool. Returns the transcript text.",
    parameters={
        "type": "object",
        "properties": {
            "audio_url": {"type": "string"},
            "max_bytes": {"type": "integer", "default": 80_000_000, "description": "Cap before transcription (~80 MB)."},
            "model_size": {"type": "string", "default": "base", "enum": ["tiny", "base", "small", "medium"]},
        },
        "required": ["audio_url"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="podcast",
)
async def podcast_transcribe(audio_url: str, max_bytes: int = 80_000_000, model_size: str = "base") -> Dict[str, Any]:
    # Reuse podcast.download then voice_local.whisper.
    from plugins.podcast.plugin import podcast_download as _download
    from plugins.voice_local.plugin import voice_stt_whisper_local as _stt
    import base64 as _b64

    dl = await _download(audio_url, max_bytes=max_bytes)
    if not dl.get("ok"):
        return dl
    try:
        audio_bytes = Path(dl["file"]).read_bytes()
        b64 = _b64.b64encode(audio_bytes).decode("ascii")
        stt_result = await _stt(audio_base64=b64, model_size=model_size)
        if not stt_result.get("ok"):
            return stt_result
        return {
            "ok": True,
            "audio_file": dl["file"],
            "audio_bytes": dl["bytes"],
            "transcript": stt_result.get("text", ""),
            "language": stt_result.get("language"),
            "duration": stt_result.get("duration"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "podcast"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free podcast tools: RSS parse, episode download, transcription via local Whisper."
