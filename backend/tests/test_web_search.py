# ====================================================================
# JARVIS OMEGA — Web search tests (ddgs + Lite fallback + tool)
# ====================================================================
"""
Tests for the DuckDuckGo web search path.

ALL network access here is faked (monkeypatched ddgs + httpx
MockTransport-style stubs). No real query is ever sent: live search
is verified manually, not in the suite, so tests stay deterministic
offline.
"""

from __future__ import annotations

import pytest

from backend.services.web_search_service import (
    WebSearchService,
    web_search_service,
)

LITE_HTML = """
<html><body><table>
<tr><td><a class="result-link" href="https://example.com/a">Example A</a></td></tr>
<tr><td class="result-snippet">Snippet for A.</td></tr>
<tr><td><a class="result-link" href="https://example.com/b">Example B</a></td></tr>
<tr><td class="result-snippet">Snippet for B.</td></tr>
</table></body></html>
"""


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FakeLiteClient:
    """httpx.AsyncClient stand-in returning fixture Lite HTML."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, data=None, headers=None):
        return _FakeResp(LITE_HTML)


@pytest.fixture()
def service() -> WebSearchService:
    return WebSearchService()


def test_lite_html_parser(service):
    results = service._parse_lite_html(LITE_HTML, max_results=5)
    assert len(results) == 2
    assert results[0]["title"] == "Example A"
    assert results[0]["snippet"] == "Snippet for A."
    assert results[0]["url"] == "https://example.com/a"
    assert results[1]["title"] == "Example B"


@pytest.mark.asyncio
async def test_search_uses_ddgs_first(service, monkeypatch):
    async def fake_ddgs(query, max_results):
        return [{"title": "DDG Hit", "snippet": "from ddgs", "url": "https://ddg.example/"}]

    monkeypatch.setattr(
        "backend.services.web_search_service._search_ddgs_sync",
        lambda query, max_results: [{"title": "DDG Hit", "snippet": "from ddgs", "url": "https://ddg.example/"}],
    )
    results = await service.search("test query", max_results=3)
    assert len(results) == 1
    assert results[0]["title"] == "DDG Hit"
    assert results[0]["url"] == "https://ddg.example/"


@pytest.mark.asyncio
async def test_search_falls_back_to_lite_html(service, monkeypatch):
    def failing_ddgs(query, max_results):
        raise RuntimeError("ddgs unavailable")

    monkeypatch.setattr(
        "backend.services.web_search_service._search_ddgs_sync", failing_ddgs
    )
    monkeypatch.setattr(
        "backend.services.web_search_service.httpx.AsyncClient", _FakeLiteClient
    )
    results = await service.search("test query", max_results=5)
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/a"


@pytest.mark.asyncio
async def test_search_and_summarize_format(service, monkeypatch):
    async def fake_search(query, max_results=5):
        return [{"title": "T", "snippet": "S", "url": "https://x.example/"}]

    monkeypatch.setattr(service, "search", fake_search)
    text = await service.search_and_summarize("hello")
    assert "[WEB SEARCH RESULTS for: 'hello']" in text
    assert "Title: T" in text
    assert "Source: https://x.example/" in text


@pytest.mark.asyncio
async def test_fetch_page_uses_scrapling(service, monkeypatch):
    """fetch_page wraps Fetcher.get + page.markdown() (monkeypatched)."""
    import backend.services.web_search_service as svc

    class _FakePage:
        status = 200
        url = "https://example.com/page"

        def markdown(self, main_content_only=False):
            return "# Example Page\n\nSome readable text here."

    class _FakeFetcher:
        @staticmethod
        def get(url, timeout=30):
            return _FakePage()

    monkeypatch.setattr(svc, "_fetch_scrapling_sync", lambda url, max_chars: {
        "ok": True, "url": url, "final_url": url, "title": "Example Page",
        "text": "# Example Page\n\nSome readable text here.",
        "chars": 40, "truncated": False,
    })
    page = await service.fetch_page("https://example.com/page")
    assert page["ok"] is True
    assert page["title"] == "Example Page"
    assert "readable text" in page["text"]


@pytest.mark.asyncio
async def test_fetch_page_failure_never_raises(service, monkeypatch):
    def failing_fetch(url, max_chars):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "backend.services.web_search_service._fetch_scrapling_sync", failing_fetch
    )
    page = await service.fetch_page("https://example.com/page")
    assert page["ok"] is False
    assert page["text"] == ""
    assert "network down" in str(page.get("error", ""))


@pytest.mark.asyncio
async def test_search_fetch_and_summarize(service, monkeypatch):
    """Search, then fetch top results; fetched Markdown lands in context."""
    async def fake_search(query, max_results=5):
        return [
            {"title": "T1", "snippet": "S1", "url": "https://a.example/"},
            {"title": "T2", "snippet": "S2", "url": "https://b.example/"},
        ]

    async def fake_fetch(url, max_chars=12000):
        return {
            "ok": True, "url": url, "final_url": url, "title": "Fetched " + url,
            "text": "fetched markdown body", "chars": 21, "truncated": False,
        }

    monkeypatch.setattr(service, "search", fake_search)
    monkeypatch.setattr(service, "fetch_page", fake_fetch)
    text = await service.search_fetch_and_summarize("hello", fetch_top=2)
    assert "[WEB SEARCH RESULTS for: 'hello']" in text
    assert "Title: T1" in text
    assert "[FETCHED PAGES" in text
    assert "fetched markdown body" in text


@pytest.mark.asyncio
async def test_search_fetch_skips_failed_pages(service, monkeypatch):
    async def fake_search(query, max_results=5):
        return [{"title": "T", "snippet": "S", "url": "https://x.example/"}]

    async def failing_fetch(url, max_chars=12000):
        return {"ok": False, "url": url, "final_url": url, "title": "",
                "text": "", "chars": 0, "truncated": False, "error": "boom"}

    monkeypatch.setattr(service, "search", fake_search)
    monkeypatch.setattr(service, "fetch_page", failing_fetch)
    text = await service.search_fetch_and_summarize("hello")
    assert "Title: T" in text
    assert "no pages could be fetched" in text


def test_web_search_tool_registered():
    import plugins.web.plugin  # noqa: F401  (import registers the tools)

    from backend.tools import get_registry

    tool = get_registry().get("web.search")
    assert tool is not None
    assert tool.category == "web"
    assert "query" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_web_search_tool_calls_service(monkeypatch):
    import plugins.web.plugin as web_plugin

    async def fake_search(query, max_results=5):
        return [{"title": "T", "snippet": "S", "url": "https://x.example/"}]

    monkeypatch.setattr(web_search_service, "search", fake_search)
    out = await web_plugin.web_search("hello", max_results=3)
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["results"][0]["url"] == "https://x.example/"


def test_web_scrape_tool_registered():
    import plugins.web.plugin  # noqa: F401  (import registers the tools)

    from backend.tools import get_registry

    tool = get_registry().get("web.scrape")
    assert tool is not None
    assert tool.category == "web"
    assert "url" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_web_scrape_tool_calls_service(monkeypatch):
    import plugins.web.plugin as web_plugin

    async def fake_fetch(self, url, max_chars=12000):
        return {
            "ok": True, "url": url, "final_url": url, "title": "Example",
            "text": "page markdown", "chars": 13, "truncated": False,
        }

    monkeypatch.setattr(
        "backend.services.web_search_service.WebSearchService.fetch_page", fake_fetch
    )
    out = await web_plugin.web_scrape("https://example.com/page")
    assert out["ok"] is True
    assert out["title"] == "Example"
    assert out["text"] == "page markdown"


@pytest.mark.asyncio
async def test_web_scrape_tool_rejects_bad_url():
    import plugins.web.plugin as web_plugin

    out = await web_plugin.web_scrape("not-a-url")
    assert out["ok"] is False


def test_needs_web_search_arabic_triggers():
    from backend.services.llm_service import _needs_web_search

    assert _needs_web_search("ما هو طقس إربد اليوم؟") is True
    assert _needs_web_search("آخر أخبار الذكاء الاصطناعي") is True
    assert _needs_web_search("كم سعر البيتكوين؟") is True
    assert _needs_web_search("what is the weather today?") is True
    assert _needs_web_search("مرحبا كيف حالك") is False
    assert _needs_web_search("hello there") is False


def test_frontend_config_and_api_wiring():
    """config.js exists with the override var; index.html reads it."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent.parent
    config = (repo / "frontend" / "config.js").read_text(encoding="utf-8")
    assert 'window.JARVIS_API_URL = "";' in config
    assert "Render backend URL" in config

    html = (repo / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/config.js"></script>' in html
    assert "window.JARVIS_API_URL" in html
    assert "API.replace(/^http/, 'ws') + '/ws/ui'" in html
