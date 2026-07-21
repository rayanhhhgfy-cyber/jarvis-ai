# ====================================================================
# JARVIS OMEGA — Free Web Plugin (URL fetch + Wikipedia + arXiv + RSS + HN)
# ====================================================================
"""
Phase 10 plugin: free public-API integrations. No API keys required.

  * ``web.fetch``           — GET a URL, return body as text.
  * ``web.extract_article`` — Trafilatura-based article extractor (returns
                              clean text without nav/ads/footer noise).
  * ``web.wikipedia``       — Wikipedia REST API.
  * ``web.arxiv``           — arXiv search + abstract retrieval.
  * ``web.rss``             — Parse any RSS/Atom feed.
  * ``web.hackernews``      — Top/Ask/Show HN stories.

All HTTP calls go through ``httpx.AsyncClient`` with sensible timeouts.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

import httpx

from backend.tools import tool, RiskTier


_USER_AGENT = "JARVIS-OMEGA/1.0 (+https://github.com/google-deepmind/jarvis-omega)"


# --------------------------------------------------------------------
# Plain URL fetch
# --------------------------------------------------------------------

@tool(
    name="web.fetch",
    description="GET a URL and return the response body as text (truncated to 50 KB).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "timeout": {"type": "number", "default": 15.0},
            "max_chars": {"type": "integer", "default": 50000},
        },
        "required": ["url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="web",
)
async def web_fetch(url: str, timeout: float = 15.0, max_chars: int = 50000) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
        text = resp.text[:max_chars]
        return {
            "ok": True,
            "status": resp.status_code,
            "url": str(resp.url),
            "content_type": resp.headers.get("content-type", ""),
            "body": text,
            "truncated": len(resp.text) > max_chars,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


# --------------------------------------------------------------------
# Article extraction (Trafilatura)
# --------------------------------------------------------------------

@tool(
    name="web.extract_article",
    description="Fetch a URL and extract the main article text using Trafilatura (no nav/ads/footer). Returns clean text.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "include_links": {"type": "boolean", "default": False},
            "max_chars": {"type": "integer", "default": 20000},
        },
        "required": ["url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="web",
)
async def web_extract_article(url: str, include_links: bool = False, max_chars: int = 20000) -> Dict[str, Any]:
    try:
        import trafilatura  # type: ignore
    except ImportError:
        return {"ok": False, "error": "trafilatura is not installed — add to requirements.txt"}
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        extracted = trafilatura.extract(
            resp.text,
            include_links=include_links,
            include_tables=True,
            favor_recall=True,
        )
        if not extracted:
            return {"ok": False, "error": "trafilatura could not extract article content"}
        return {
            "ok": True,
            "url": url,
            "text": extracted[:max_chars],
            "truncated": len(extracted) > max_chars,
            "chars": len(extracted),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Wikipedia
# --------------------------------------------------------------------

@tool(
    name="web.wikipedia",
    description="Look up a topic on Wikipedia and return the summary (and optionally full page).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Topic to look up."},
            "lang": {"type": "string", "default": "en"},
            "full": {"type": "boolean", "default": False, "description": "Return full page text instead of summary."},
            "max_chars": {"type": "integer", "default": 10000},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="web",
)
async def web_wikipedia(query: str, lang: str = "en", full: bool = False, max_chars: int = 10000) -> Dict[str, Any]:
    base = f"https://{lang}.wikipedia.org/w/api.php"
    # Step 1: find the best-matching article title.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            search = await client.get(base, params={
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": 1, "format": "json",
            })
            search_data = search.json()
            hits = search_data.get("query", {}).get("search", [])
            if not hits:
                return {"ok": False, "error": f"no Wikipedia article matching '{query}'"}
            title = hits[0]["title"]

            # Step 2: get summary or full content via the REST API.
            rest_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
            summary_resp = await client.get(rest_url, headers={"User-Agent": _USER_AGENT})
            summary = summary_resp.json()
            text = summary.get("extract", "")
            if full:
                # Use the plaintext extracts endpoint for full article.
                extract_resp = await client.get(base, params={
                    "action": "query", "prop": "extracts",
                    "explaintext": 1, "titles": title, "format": "json",
                })
                ext_data = extract_resp.json()
                pages = ext_data.get("query", {}).get("pages", {})
                if pages:
                    page = next(iter(pages.values()))
                    text = page.get("extract", "") or text
        return {
            "ok": True,
            "title": title,
            "url": summary.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------

@tool(
    name="web.arxiv",
    description="Search arXiv for academic preprints. Returns list of {title, authors, abstract, pdf_url}.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms."},
            "max_results": {"type": "integer", "default": 5},
            "sort_by": {"type": "string", "enum": ["relevance", "lastUpdatedDate", "submittedDate"], "default": "relevance"},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="web",
)
async def web_arxiv(query: str, max_results: int = 5, sort_by: str = "relevance") -> Dict[str, Any]:
    try:
        url = "http://export.arxiv.org/api/query"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params={
                "search_query": f"all:{query}",
                "start": 0, "max_results": max_results,
                "sortBy": sort_by, "sortOrder": "descending",
            })
        # Parse Atom feed.
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        entries = []
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            published_el = entry.find("atom:published", ns)
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns) if a.find("atom:name", ns) is not None]
            pdf_url = ""
            for link in entry.findall("atom:link", ns):
                if link.attrib.get("title") == "pdf":
                    pdf_url = link.attrib.get("href", "")
                    break
            entries.append({
                "title": (title_el.text or "").strip().replace("\n", " "),
                "authors": authors,
                "abstract": (summary_el.text or "").strip()[:2000],
                "published": (published_el.text or "").strip() if published_el is not None else "",
                "pdf_url": pdf_url,
            })
        return {"ok": True, "count": len(entries), "entries": entries}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# RSS / Atom
# --------------------------------------------------------------------

@tool(
    name="web.rss",
    description="Parse an RSS or Atom feed and return recent entries.",
    parameters={
        "type": "object",
        "properties": {
            "feed_url": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["feed_url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="web",
)
async def web_rss(feed_url: str, limit: int = 10) -> Dict[str, Any]:
    try:
        import feedparser  # type: ignore
    except ImportError:
        return {"ok": False, "error": "feedparser not installed — add to requirements.txt"}
    try:
        # feedparser is sync; fetch the body async then parse.
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": _USER_AGENT})
        parsed = feedparser.parse(resp.content)
        entries = []
        for e in parsed.entries[:limit]:
            entries.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "published": e.get("published", e.get("updated", "")),
                "summary": (e.get("summary", "") or "")[:500],
                "author": e.get("author", ""),
            })
        return {
            "ok": True,
            "feed_title": parsed.feed.get("title", ""),
            "count": len(entries),
            "entries": entries,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Hacker News
# --------------------------------------------------------------------

@tool(
    name="web.hackernews",
    description="Get top stories from Hacker News. Returns list of {title, url, score, by}.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["top", "new", "ask", "show", "best"], "default": "top"},
            "limit": {"type": "integer", "default": 10},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="web",
)
async def web_hackernews(category: str = "top", limit: int = 10) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            ids_resp = await client.get(f"https://hacker-news.firebaseio.com/v0/{category}stories.json")
            ids = ids_resp.json()[:limit]
            stories = []
            for sid in ids:
                item_resp = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                item = item_resp.json()
                if not item:
                    continue
                stories.append({
                    "id": sid,
                    "title": item.get("title", ""),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                    "score": item.get("score", 0),
                    "by": item.get("by", ""),
                    "time": item.get("time", 0),
                    "descendants": item.get("descendants", 0),
                })
        return {"ok": True, "category": category, "count": len(stories), "stories": stories}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "web"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free web tools: URL fetch, article extraction, Wikipedia, arXiv, RSS, Hacker News."
