# Phase 19: Podcast Auto-Publisher (REAL)
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="podcast.generate_rss", description="Generate a podcast RSS feed XML from episode list.", parameters={"type":"object","properties":{"podcast_name":{"type":"string"},"episodes":{"type":"array","items":{"type":"object"},"default":[]}},"required":["podcast_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="podcast_publisher")
async def generate_rss(podcast_name: str, episodes: list = None) -> Dict[str, Any]:
    episodes = episodes or []
    items = ""
    for ep in episodes:
        items += f"""<item><title>{ep.get("title","")}</title><description>{ep.get("description","")}</description><enclosure url="{ep.get("audio_url","")}" type="audio/mpeg"/><pubDate>{ep.get("date",datetime.utcnow().strftime("%a, %d %b %Y"))}</pubDate></item>"""
    rss = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{podcast_name}</title><description>Podcast by JARVIS OMEGA</description><language>ar</language>{items}</channel></rss>"""
    out = Path("./storage/podcast/feed.xml"); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rss, encoding="utf-8")
    return {"ok": True, "rss_path": str(out), "episodes": len(episodes)}

@tool(name="podcast.publish_anchor", description="Guide for publishing podcast on Anchor (free, distributes to Spotify + Apple).", parameters={"type":"object","properties":{"episode_path":{"type":"string"}},"required":["episode_path"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="podcast_publisher")
async def publish_anchor(episode_path: str) -> Dict[str, Any]:
    import webbrowser; webbrowser.open("https://podcasters.spotify.com/pod/dashboard/episode/new")
    return {"ok": True, "url": "https://podcasters.spotify.com", "instructions": ["1. Sign up at podcasters.spotify.com (FREE)", "2. Click New Episode", "3. Upload audio file", "4. Add title + description", "5. Publish — goes to Spotify + Apple + Google automatically"]}

PLUGIN_NAME = "podcast_publisher"; PLUGIN_VERSION = "1.0.0"
