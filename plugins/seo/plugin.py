# ====================================================================
# JARVIS OMEGA - SEO + Rank Tracking Plugin (Phase 13)
# ====================================================================
"""
Track Google rankings, audit backlinks, research keywords.

  seo.rank_check        - find your position for a keyword
  seo.backlink_audit    - free backlink discovery via Google
  seo.keyword_research  - Google Suggest API
  seo.competitor_gap    - keyword gap analysis
  seo.content_brief     - LLM brief for ranking
  seo.serp_snapshot     - daily snapshot of a SERP
  seo.sitemap_submit    - ping Google/Bing
"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]


def _rand_ua() -> str:
    return random.choice(_USER_AGENTS)


async def _google_search(query: str, num: int = 50) -> List[Dict[str, str]]:
    """Scrape Google SERP (top N results) using rotating UA + delay."""
    try:
        # 8-second courtesy delay between calls.
        await _maybe_throttle()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": query, "num": num, "hl": "en"},
                headers={"User-Agent": _rand_ua(), "Accept-Language": "en-US,en;q=0.9"},
            )
        # Parse <a href="/url?q=...">
        results = []
        for m in re.finditer(r'<a href="/url\?q=([^&"]+)', resp.text):
            url = urllib.parse.unquote(m.group(1))
            if url.startswith("http") and "google." not in url:
                if url not in [r["url"] for r in results]:
                    results.append({"url": url})
            if len(results) >= num:
                break
        return results
    except Exception:
        return []


_last_google_call = 0.0


async def _maybe_throttle(min_gap_s: float = 8.0) -> None:
    global _last_google_call
    now = time.time()
    wait = _last_google_call + min_gap_s - now
    if wait > 0:
        import asyncio
        await asyncio.sleep(wait)
    _last_google_call = time.time()


# --------------------------------------------------------------------
# Rank check
# --------------------------------------------------------------------

@tool(
    name="seo.rank_check",
    description="Check your position in Google for a keyword. Returns position (1-100) + URL found.",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "domain": {"type": "string", "description": "Your site (e.g. 'example.com')."},
            "depth": {"type": "integer", "default": 100, "description": "How many results to scan."},
        },
        "required": ["keyword", "domain"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="seo",
)
async def seo_rank_check(keyword: str, domain: str, depth: int = 100) -> Dict[str, Any]:
    domain = domain.lower().lstrip("https://").lstrip("http://").rstrip("/")
    results = await _google_search(keyword, num=depth)
    for i, r in enumerate(results, start=1):
        if domain in r["url"].lower():
            # Persist history.
            try:
                business_db.execute(
                    "INSERT INTO rank_history (keyword, url, position, date) VALUES (?, ?, ?, ?)",
                    (keyword, r["url"], i, datetime.utcnow().isoformat()),
                )
            except Exception:
                pass
            return {
                "ok": True, "keyword": keyword, "domain": domain,
                "position": i, "url": r["url"], "depth": depth,
            }
    return {"ok": True, "keyword": keyword, "domain": domain, "position": None, "depth": depth, "note": f"not in top {depth}"}


# --------------------------------------------------------------------
# Backlink audit
# --------------------------------------------------------------------

@tool(
    name="seo.backlink_audit",
    description="Discover backlinks to a domain via Google's `link:` operator. Returns a list of linking URLs.",
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
        },
        "required": ["domain"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="seo",
)
async def seo_backlink_audit(domain: str, limit: int = 50) -> Dict[str, Any]:
    results = await _google_search(f'"{domain}"', num=limit)
    # Filter to URLs that actually link back (heuristic — anything that mentions the domain).
    backlinks = [r for r in results if domain not in r["url"].lower()]
    return {
        "ok": True, "domain": domain, "backlinks_found": len(backlinks),
        "backlinks": backlinks[:limit],
        "note": "Google's `link:` operator is mostly deprecated; this uses the broad domain-mention approach. Use Ahrefs/SEMrush free trials for fuller coverage.",
    }


# --------------------------------------------------------------------
# Keyword research
# --------------------------------------------------------------------

@tool(
    name="seo.keyword_research",
    description="Get keyword suggestions from Google Suggest API. Free.",
    parameters={
        "type": "object",
        "properties": {
            "seed_keyword": {"type": "string"},
            "language": {"type": "string", "default": "ar", "description": "ISO code, e.g. 'ar', 'en'."},
            "country": {"type": "string", "default": "jo", "description": "ISO code, e.g. 'jo', 'us'."},
        },
        "required": ["seed_keyword"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="seo",
)
async def seo_keyword_research(seed_keyword: str, language: str = "ar", country: str = "jo") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://suggestqueries.google.com/complete/search",
                params={
                    "client": "chrome",
                    "q": seed_keyword,
                    "hl": f"{language}-{country.upper()}",
                    "gl": country,
                },
            )
        data = resp.json()
        suggestions = data[1] if len(data) > 1 else []
        return {"ok": True, "seed": seed_keyword, "suggestions": suggestions, "count": len(suggestions)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Competitor gap
# --------------------------------------------------------------------

@tool(
    name="seo.competitor_gap",
    description="Find keywords a competitor ranks for that you don't. Uses LLM + backlink-style discovery.",
    parameters={
        "type": "object",
        "properties": {
            "your_domain": {"type": "string"},
            "competitor_domain": {"type": "string"},
            "niche": {"type": "string"},
        },
        "required": ["your_domain", "competitor_domain", "niche"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="seo",
)
async def seo_competitor_gap(your_domain: str, competitor_domain: str, niche: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Niche: {niche}\nMy domain: {your_domain}\nCompetitor: {competitor_domain}",
            system_instructions=(
                "You are a senior SEO strategist. Output STRICT JSON: "
                "{\"missing_keywords\": [string, ...], \"content_ideas\": [string, ...], "
                "\"quick_wins\": [string, ...]}. 15-25 keywords my competitor ranks for that I likely don't."
            ),
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
        import json
        parsed = json.loads(text)
        return {"ok": True, "your_domain": your_domain, "competitor_domain": competitor_domain, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Content brief
# --------------------------------------------------------------------

@tool(
    name="seo.content_brief",
    description="Generate a content brief for ranking a page on a keyword.",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["keyword"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="seo",
)
async def seo_content_brief(keyword: str, language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Target keyword: {keyword}",
            system_instructions=(
                f"You are a senior content SEO strategist. Output a brief in {'Arabic' if language == 'ar' else 'English'} "
                "as STRICT JSON: "
                "{\"title_suggestion\": string, \"word_count_target\": integer, "
                "\"search_intent\": \"informational|transactional|navigational|commercial\", "
                "\"must_cover_topics\": [string], \"suggested_headers\": [string], "
                "\"internal_link_anchors\": [string], \"schema_type\": string, "
                "\"meta_description\": string}."
            ),
            inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"):
            text = text[4:]
        import json
        return {"ok": True, "keyword": keyword, "brief": json.loads(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# SERP snapshot
# --------------------------------------------------------------------

@tool(
    name="seo.serp_snapshot",
    description="Take a snapshot of the current Google SERP for a keyword (top 20 results + visible URLs).",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "depth": {"type": "integer", "default": 20},
        },
        "required": ["keyword"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="seo",
)
async def seo_serp_snapshot(keyword: str, depth: int = 20) -> Dict[str, Any]:
    results = await _google_search(keyword, num=depth)
    return {
        "ok": True,
        "keyword": keyword,
        "snapshot_at": datetime.utcnow().isoformat(),
        "top_results": [{"position": i + 1, "url": r["url"]} for i, r in enumerate(results)],
    }


# --------------------------------------------------------------------
# Sitemap submit
# --------------------------------------------------------------------

@tool(
    name="seo.sitemap_submit",
    description="Ping Google + Bing with your sitemap URL for faster indexing.",
    parameters={
        "type": "object",
        "properties": {
            "sitemap_url": {"type": "string"},
        },
        "required": ["sitemap_url"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="seo",
)
async def seo_sitemap_submit(sitemap_url: str) -> Dict[str, Any]:
    out = {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            google = await client.get(
                "https://www.google.com/ping",
                params={"sitemap": sitemap_url},
            )
            out["google_status"] = google.status_code
    except Exception as e:
        out["google_error"] = str(e)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            bing = await client.post(
                "https://www.bing.com/ping",
                data={"sitemap": sitemap_url},
            )
            out["bing_status"] = bing.status_code
    except Exception as e:
        out["bing_error"] = str(e)
    out["ok"] = "google_status" in out or "bing_status" in out
    out["sitemap_url"] = sitemap_url
    return out


PLUGIN_NAME = "seo"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free SEO tools: rank tracking, backlinks, keyword research, content briefs, sitemap submission."
