# ====================================================================
# JARVIS OMEGA — Web Search Service
# ====================================================================
"""
Provides real-time web search capability.

Primary engine: the ``ddgs`` library (DuckDuckGo, keyless, free, no API
key). Falls back to DuckDuckGo Lite HTML scraping when ddgs is
unavailable or raises, so search keeps working offline of the library.
Returns structured results with titles, snippets, and URLs.
"""

from __future__ import annotations

import asyncio
import re
from typing import List, Dict, Optional

import httpx

from shared.logger import get_logger

log = get_logger("web_search")


def _search_ddgs_sync(query: str, max_results: int) -> List[Dict[str, str]]:
    """Blocking ddgs call (runs in a thread via asyncio.to_thread).

    Tries backends in order and returns the first non-empty result set.
    The "auto" backend picks randomly and can land on backends that are
    unreachable from a given network (DNS/stream errors), so explicit
    ordered attempts are more reliable. Raises if every backend fails.
    """
    from ddgs import DDGS

    last_error: Exception | None = None
    for backend in ("duckduckgo", "bing", "brave", "google"):
        try:
            with DDGS(timeout=15) as ddgs:
                rows = list(ddgs.text(query, max_results=max_results, backend=backend))
            results: List[Dict[str, str]] = []
            for row in rows:
                title = (row.get("title") or "").strip()
                url = (row.get("href") or "").strip()
                snippet = (row.get("body") or "").strip()
                if title and url:
                    results.append({"title": title, "snippet": snippet, "url": url})
            if results:
                return results
        except Exception as e:  # noqa: BLE001 - try the next backend
            last_error = e
            log.warning("web_search_ddgs_backend_failed", backend=backend, error=str(e))
            continue
    if last_error is not None:
        raise last_error
    return []


def _search_ddgs_news_sync(query: str, max_results: int) -> List[Dict[str, str]]:
    """Blocking ddgs.news call (runs in a thread via asyncio.to_thread).

    The news endpoint returns real articles — headline, body, source,
    date — instead of the generic web results ddgs.text returns for
    broad queries (section homepages, Wikipedia, brand pages). That
    is what the morning briefing needs. Raises if every backend fails.
    """
    from ddgs import DDGS

    last_error: Exception | None = None
    for backend in ("duckduckgo", "bing", "brave", "google"):
        try:
            with DDGS(timeout=15) as ddgs:
                rows = list(ddgs.news(query, max_results=max_results, backend=backend))
            results: List[Dict[str, str]] = []
            for row in rows:
                title = (row.get("title") or "").strip()
                url = (row.get("url") or "").strip()
                snippet = (row.get("body") or "").strip()
                if title and url:
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": url,
                        "source": (row.get("source") or "").strip(),
                        "date": (row.get("date") or "").strip(),
                    })
            if results:
                return results
        except Exception as e:  # noqa: BLE001 - try the next backend
            last_error = e
            log.warning("web_search_ddgs_news_backend_failed", backend=backend, error=str(e))
            continue
    if last_error is not None:
        raise last_error
    return []


def _fetch_scrapling_sync(url: str, max_chars: int) -> Dict[str, object]:
    """Blocking Scrapling fetch (runs in a thread via asyncio.to_thread).

    Fetcher.get + page.markdown(main_content_only=True) returns clean
    Markdown with scripts/styles/hidden content stripped. Raises on
    network errors or non-200 status so the caller can skip the page.
    """
    from scrapling.fetchers import Fetcher

    page = Fetcher.get(url, timeout=30)
    status = getattr(page, "status", 200)
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    markdown = page.markdown(main_content_only=True) or ""
    text = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    truncated = len(text) > max_chars
    title = ""
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
    return {
        "ok": True,
        "url": url,
        "final_url": str(getattr(page, "url", url)),
        "title": title,
        "text": text[:max_chars],
        "chars": min(len(text), max_chars),
        "truncated": truncated,
    }


class WebSearchService:
    """
    Searches the web via ddgs (DuckDuckGo, keyless) with a DuckDuckGo
    Lite HTML fallback. No API key required. Returns structured results
    with titles, snippets, and URLs.
    """

    def __init__(self) -> None:
        self._search_url = "https://lite.duckduckgo.com/lite/"
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    async def get_ip_location(self) -> Optional[str]:
        """Get the user's current city/region/country based on public IP address."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("https://ipapi.co/json/")
                if resp.status_code == 200:
                    data = resp.json()
                    city = data.get("city")
                    region = data.get("region")
                    country = data.get("country_name")
                    if city:
                        return f"{city}, {region}, {country}" if region else f"{city}, {country}"
        except Exception as e:
            log.warning(f"Failed to fetch IP location from ipapi.co: {e}")
            
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("http://ip-api.com/json/")
                if resp.status_code == 200:
                    data = resp.json()
                    city = data.get("city")
                    region = data.get("regionName")
                    country = data.get("country")
                    if city:
                        return f"{city}, {region}, {country}" if region else f"{city}, {country}"
        except Exception as e:
            log.warning(f"Failed to fetch IP location from ip-api.com: {e}")
            
        return None

    async def news(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Real news articles for a query, via ddgs.news.

        Returns [{"title", "snippet", "url", "source", "date"}] — actual
        headlines, not the section homepages a plain text search
        returns for broad queries. Empty (never raises) when the news
        endpoint fails, so the caller can fall back to a plain search.
        """
        try:
            results = await asyncio.to_thread(_search_ddgs_news_sync, query, max_results)
            if results:
                log.info("web_search_news_results", count=len(results))
                return results
        except Exception as e:
            log.warning("web_search_news_failed", error=str(e))
        return []

    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Perform a web search and return a list of result dicts:
        [{"title": ..., "snippet": ..., "url": ...}, ...]

        Tries ddgs first; on any failure (library missing, network/DNS
        error, empty results) falls back to DuckDuckGo Lite HTML scraping.
        """
        log.info("web_search_start", query=query)
        results: List[Dict[str, str]] = []

        try:
            results = await asyncio.to_thread(_search_ddgs_sync, query, max_results)
            if results:
                log.info("web_search_results", engine="ddgs", count=len(results))
                return results
            log.warning("web_search_ddgs_empty_falling_back", query=query)
        except Exception as e:
            log.warning("web_search_ddgs_failed_falling_back", error=str(e))

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.post(
                    self._search_url,
                    data={"q": query, "kl": ""},
                    headers=self._headers,
                )

                if resp.status_code != 200:
                    log.error("web_search_http_error", status=resp.status_code)
                    return results

                html = resp.text
                results = self._parse_lite_html(html, max_results)
                log.info("web_search_results", engine="lite-html", count=len(results))

        except Exception as e:
            log.error("web_search_failed", error=str(e))

        return results

    async def get_weather(self, location: str) -> str:
        """Convenience method specifically for weather queries."""
        results = await self.search(f"weather in {location} today current temperature", max_results=3)
        if not results:
            return f"I was unable to retrieve weather data for {location} at this time."

        # Combine top result snippets
        weather_info = "\n".join(
            f"• {r['snippet']}" for r in results if r.get("snippet")
        )
        return weather_info or f"Search returned results but no weather snippet for {location}."

    async def search_and_summarize(self, query: str) -> str:
        """
        Search the web and return a formatted context block
        that can be injected into the LLM prompt.
        """
        results = await self.search(query, max_results=5)

        if not results:
            return "No web search results found for this query."

        lines = [f"[WEB SEARCH RESULTS for: '{query}']"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n--- Result {i} ---")
            if r.get("title"):
                lines.append(f"Title: {r['title']}")
            if r.get("snippet"):
                lines.append(f"Content: {r['snippet']}")
            if r.get("url"):
                lines.append(f"Source: {r['url']}")

        return "\n".join(lines)

    async def fetch_page(self, url: str, max_chars: int = 12000) -> Dict[str, object]:
        """
        Fetch a page with Scrapling and return its readable Markdown.

        Fetcher.get + page.markdown(main_content_only=True): scripts,
        styles and hidden content are stripped by the library. Returns
        {"ok", "url", "final_url", "title", "text", "chars", "truncated"}
        (or {"ok": False, "error": ...} on failure — never raises).
        """
        try:
            result = await asyncio.to_thread(_fetch_scrapling_sync, url, max_chars)
            log.info("web_fetch_page_ok", url=url, chars=result["chars"])
            return result
        except Exception as e:
            log.warning("web_fetch_page_failed", url=url, error=str(e))
            return {
                "ok": False, "url": url, "final_url": url,
                "title": "", "text": "", "chars": 0, "truncated": False,
                "error": str(e),
            }

    async def search_fetch_and_summarize(
        self, query: str, max_results: int = 5, fetch_top: int = 3
    ) -> str:
        """
        Search, then Scrapling-fetch the top ``fetch_top`` results and
        return a combined context block (search snippets + fetched page
        Markdown) for the LLM. Pages that fail to fetch are skipped,
        never fatal.
        """
        results = await self.search(query, max_results=max_results)
        if not results:
            return "No web search results found for this query."

        lines = [f"[WEB SEARCH RESULTS for: '{query}']"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n--- Result {i} ---")
            if r.get("title"):
                lines.append(f"Title: {r['title']}")
            if r.get("snippet"):
                lines.append(f"Content: {r['snippet']}")
            if r.get("url"):
                lines.append(f"Source: {r['url']}")

        lines.append("\n[FETCHED PAGES — full readable text]")
        fetched_any = False
        for r in results[:fetch_top]:
            url = r.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            page = await self.fetch_page(url)
            if not page.get("ok") or not page.get("text"):
                continue
            fetched_any = True
            lines.append(f"\n--- Page: {page.get('title') or url} ({url}) ---")
            lines.append(str(page["text"]))
        if not fetched_any:
            lines.append("(no pages could be fetched; answer from the snippets above)")

        return "\n".join(lines)

    def _parse_lite_html(self, html: str, max_results: int) -> List[Dict[str, str]]:
        """Parse DuckDuckGo Lite HTML for search results."""
        results: List[Dict[str, str]] = []

        # DuckDuckGo Lite uses table rows with class "result-link" and "result-snippet"
        # Extract links
        link_pattern = re.compile(
            r'<a[^>]+class="result-link"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        snippet_pattern = re.compile(
            r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE,
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i in range(min(len(links), max_results)):
            url, raw_title = links[i]
            title = re.sub(r"<[^>]+>", "", raw_title).strip()
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()

            if url and title:
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                })

        # Fallback: if the lite parser didn't find structured results,
        # try a broader regex to grab any useful text
        if not results:
            # Try to grab any <a> tags with http links followed by text
            fallback_pattern = re.compile(
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                re.DOTALL,
            )
            raw_matches = fallback_pattern.findall(html)
            seen_urls = set()
            for url, raw_title in raw_matches:
                if "duckduckgo" in url.lower():
                    continue
                clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
                if url not in seen_urls and clean_title and len(clean_title) > 5:
                    seen_urls.add(url)
                    results.append({
                        "title": clean_title,
                        "snippet": "",
                        "url": url,
                    })
                    if len(results) >= max_results:
                        break

        return results


# Global web search service instance
web_search_service = WebSearchService()
