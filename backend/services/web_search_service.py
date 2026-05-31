# ====================================================================
# JARVIS OMEGA — Web Search Service
# ====================================================================
"""
Provides real-time web search capability using DuckDuckGo Lite (no API key).
JARVIS can use this to answer weather, news, sports, stocks, and general
knowledge questions with live data instead of hallucinating.
"""

from __future__ import annotations

import re
from typing import List, Dict, Optional

import httpx

from shared.logger import get_logger

log = get_logger("web_search")


class WebSearchService:
    """
    Searches the web via DuckDuckGo Lite HTML scraping.
    No API key required. Returns structured results with titles,
    snippets, and URLs.
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

    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Perform a web search and return a list of result dicts:
        [{"title": ..., "snippet": ..., "url": ...}, ...]
        """
        log.info("web_search_start", query=query)
        results: List[Dict[str, str]] = []

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
                log.info("web_search_results", count=len(results))

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
