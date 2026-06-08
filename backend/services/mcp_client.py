"""
MCP Client — httpx retry interceptor, SOCKS5 proxy, 3-stream parallel query.

# pip install: httpx[socks], beautifulsoup4
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from shared.logger import get_logger

log = get_logger("mcp_client")

_RETRY_DELAYS = [1.0, 3.0, 7.0]
_PARALLEL_STREAMS = 3


class MCPClient:
    """
    Multi-stream HTTP client with automatic retry,
    SOCKS5 proxy support, and parallel page fetching.
    """

    def __init__(self, proxy: Optional[str] = None):
        self._proxy = proxy
        self._client = self._build_client()

    def _build_client(self) -> httpx.AsyncClient:
        kwargs = {"timeout": 30.0, "follow_redirects": True}
        if self._proxy:
            kwargs["proxies"] = self._proxy
        return httpx.AsyncClient(**kwargs)

    async def fetch(self, url: str, headers: Optional[Dict] = None) -> Optional[str]:
        """Fetch URL with retry and exponential backoff."""
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                resp = await self._client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.text
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                if attempt < len(_RETRY_DELAYS) - 1:
                    log.info("mcp_retry", url=url[:80], attempt=attempt+1, delay=delay)
                    await asyncio.sleep(delay)
                else:
                    log.error("mcp_fetch_failed", url=url[:80], error=str(e))
                    return None

    async def parallel_fetch(self, urls: List[str]) -> List[Optional[str]]:
        """Fetch multiple URLs in parallel streams."""
        sem = asyncio.Semaphore(_PARALLEL_STREAMS)

        async def _fetch_one(url: str) -> Optional[str]:
            async with sem:
                return await self.fetch(url)

        tasks = [_fetch_one(url) for url in urls]
        return await asyncio.gather(*tasks)

    async def extract_text(self, url: str) -> Optional[str]:
        """Fetch URL and extract clean text via BeautifulSoup."""
        html = await self.fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:5000]

    async def close(self):
        await self._client.aclose()


mcp_client = MCPClient()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.mcp_client import mcp_client
# text = await mcp_client.fetch("https://example.com")
# texts = await mcp_client.parallel_fetch(["https://a.com", "https://b.com"])
# clean = await mcp_client.extract_text("https://example.com")
# ---
