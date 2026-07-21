# Phase 18: RSS-to-Content Pipeline (REAL)
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

_FEEDS_PATH = Path("./storage/rss_feeds.json")

@tool(name="rss.add_feed", description="Add an RSS feed to monitor for content ideas.", parameters={"type":"object","properties":{"url":{"type":"string"},"name":{"type":"string","default":""}},"required":["url"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="rss_content")
async def add_feed(url: str, name: str = "") -> Dict[str, Any]:
    feeds = json.loads(_FEEDS_PATH.read_text()) if _FEEDS_PATH.exists() else []
    feeds.append({"url": url, "name": name or url})
    _FEEDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FEEDS_PATH.write_text(json.dumps(feeds, indent=2), encoding="utf-8")
    return {"ok": True, "feed": url, "total_feeds": len(feeds)}

@tool(name="rss.monitor", description="Check all RSS feeds for new articles and generate content ideas from them.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="rss_content")
async def monitor() -> Dict[str, Any]:
    feeds = json.loads(_FEEDS_PATH.read_text()) if _FEEDS_PATH.exists() else []
    if not feeds: return {"ok": True, "note": "No feeds. Add with rss.add_feed."}
    ideas = []
    for feed in feeds[:5]:
        try:
            from plugins.web.plugin import web_rss
            r = await web_rss(feed_url=feed["url"], limit=3)
            if r.get("ok"):
                for entry in r.get("entries", []):
                    ideas.append({"title": entry.get("title",""), "source": feed["name"], "url": entry.get("link","")})
        except: continue
    return {"ok": True, "feeds_checked": len(feeds[:5]), "content_ideas": ideas}
