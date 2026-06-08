"""
Web search service for autonomous web research.
Uses DuckDuckGo Lite for search (no API key required) and httpx for URL fetching.
Supports:
- search_web|query
- fetch_url|url
- search_maps|query|location
- get_ip_location() → city/country
- search_and_summarize(query) → text summary of search results
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx

from shared.logger import get_logger

log = get_logger("web_search_service")

DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
DDG_API_URL = "https://api.duckduckgo.com/"
IPINFO_URL = "https://ipinfo.io/json"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


class WebSearchService:

    async def search_web(self, query: str, max_results: int = 8) -> Dict[str, Any]:
        """
        Search the web using DuckDuckGo Lite interface.
        Returns list of {title, snippet, url} results.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.post(
                    DDG_LITE_URL,
                    data={"q": query},
                    headers={"User-Agent": _USER_AGENT},
                )
                resp.raise_for_status()

            html = resp.text
            results = self._parse_ddg_lite_html(html, max_results)

            log.info("web_search_completed", query=query[:60], results=len(results))
            return {
                "success": True,
                "query": query,
                "results": results,
                "result_count": len(results),
            }
        except Exception as e:
            log.error("web_search_failed", query=query[:60], error=str(e))
            return await self._search_ddg_api(query, max_results)

    async def _search_ddg_api(self, query: str, max_results: int = 8) -> Dict[str, Any]:
        """Fallback: DuckDuckGo Instant Answer API."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                resp = await client.get(
                    DDG_API_URL,
                    params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                    headers={"User-Agent": _USER_AGENT},
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            abstract = data.get("AbstractText", "")
            if abstract:
                results.append({
                    "title": data.get("Heading", "Summary"),
                    "snippet": abstract,
                    "url": data.get("AbstractURL", ""),
                })

            for topic in data.get("RelatedTopics", [])[:max_results]:
                if "Text" in topic:
                    results.append({
                        "title": topic.get("Text", "").split(" - ")[0] if " - " in topic.get("Text", "") else topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                    })

            return {
                "success": True,
                "query": query,
                "results": results,
                "result_count": len(results),
            }
        except Exception as e:
            log.error("ddg_api_fallback_failed", error=str(e))
            return {"success": False, "query": query, "results": [], "result_count": 0, "error": str(e)}

    def _parse_ddg_lite_html(self, html: str, max_results: int) -> List[Dict[str, str]]:
        """Parse DuckDuckGo Lite HTML search results."""
        results = []
        rows = re.findall(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>\s*<br>\s*(.*?)(?:<br>|</td>)',
            html, re.DOTALL,
        )
        for url, title, snippet in rows[:max_results]:
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({
                "title": title or url,
                "snippet": snippet,
                "url": url,
            })

        if not results:
            alt_rows = re.findall(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                html, re.DOTALL,
            )
            seen = set()
            for url, title in alt_rows:
                if url in seen:
                    continue
                seen.add(url)
                if any(skip in url for skip in ("duckduckgo.com", "javascript:", "#")):
                    continue
                title = re.sub(r"<[^>]+>", "", title).strip()
                results.append({"title": title or url, "snippet": "", "url": url})
                if len(results) >= max_results:
                    break

        return results

    async def fetch_url(self, url: str, max_chars: int = 8000) -> Dict[str, Any]:
        """Fetch content from a URL and return as plain text."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
                resp.raise_for_status()

            html = resp.text
            text = self._extract_text(html)[:max_chars]

            log.info("url_fetched", url=url, length=len(text))
            return {
                "success": True,
                "url": url,
                "content": text,
                "length": len(text),
                "status_code": resp.status_code,
            }
        except Exception as e:
            log.error("url_fetch_failed", url=url, error=str(e))
            return {"success": False, "url": url, "content": "", "error": str(e)}

    async def search_maps(self, query: str, location: str = "") -> Dict[str, Any]:
        """Search for places/businesses. Uses DDG local results (free)."""
        full_query = f"{query} {location}".strip() if location else query
        return await self.search_web(full_query, max_results=10)

    async def get_ip_location(self) -> Optional[str]:
        """
        Get approximate location (city, region, country) based on IP address.
        Returns string like 'New York, US' or None.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(IPINFO_URL, headers={"User-Agent": _USER_AGENT})
                resp.raise_for_status()
                data = resp.json()
            city = data.get("city", "")
            region = data.get("region", "")
            country = data.get("country", "")
            parts = [p for p in [city, region, country] if p]
            return ", ".join(parts) if parts else None
        except Exception as e:
            log.debug("ip_location_failed", error=str(e))
            return None

    async def search_and_summarize(self, query: str, max_chars: int = 3000) -> str:
        """
        Search web for a query and return a formatted text summary.
        Used by the LLM service for automatic context injection.
        """
        result = await self.search_web(query, max_results=5)
        if not result.get("success") or not result.get("results"):
            return ""

        lines = [f"[WEB SEARCH RESULTS — {query}]"]
        for i, r in enumerate(result["results"][:5], 1):
            lines.append(f"{i}. {r['title']}")
            snippet = r.get("snippet", "")[:200]
            if snippet:
                lines.append(f"   {snippet}")
            lines.append(f"   Source: {r['url']}")

        summary = "\n".join(lines)
        return summary[:max_chars]

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        html = re.sub(r"<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&#39;", "'")
        text = re.sub(r"\s+", " ", text).strip()
        lines = text.split(". ")
        meaningful = [l.strip() for l in lines if len(l.strip()) > 40]
        return ". ".join(meaningful[:20]) if meaningful else text[:2000]


web_search_service = WebSearchService()
