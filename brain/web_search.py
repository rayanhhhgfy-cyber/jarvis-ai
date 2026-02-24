# =============================================================================
# brain/web_search.py — Web search with multiple fallback strategies
# Strategy 1: duckduckgo_search library (most reliable)
# Strategy 2: DDG Instant Answer API (JSON)
# Strategy 3: DDG Lite HTML scrape
# Strategy 4: DDG HTML search scrape
# =============================================================================

import requests
from bs4 import BeautifulSoup
from config import SEARCH_MAX_RESULTS, SEARCH_TIMEOUT

# Try to import duckduckgo_search library
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def _ddgs_search(query):
    """Use duckduckgo_search library for reliable results."""
    if not DDGS_AVAILABLE:
        return None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=SEARCH_MAX_RESULTS))
            if results:
                snippets = []
                for r in results:
                    title = r.get("title", "")
                    body = r.get("body", "")
                    if body:
                        snippets.append(f"{title}: {body}" if title else body)
                if snippets:
                    return " | ".join(snippets)
    except Exception as e:
        print(f"DDGS search error: {e}")
    return None

def _ddg_instant(query):
    """DuckDuckGo Instant Answer API."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
            headers=_HEADERS, timeout=SEARCH_TIMEOUT
        )
        data = resp.json()
        answer = (
            data.get("AbstractText") or
            data.get("Answer") or
            data.get("Definition") or ""
        ).strip()
        if answer:
            source = data.get("AbstractSource") or "DuckDuckGo"
            return answer + (f" (Source: {source})" if source else "")
    except Exception:
        pass
    return None

def _ddg_scrape(query):
    """Scrape DuckDuckGo Lite for results."""
    try:
        resp = requests.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers=_HEADERS, timeout=SEARCH_TIMEOUT
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        snippets = []
        for td in soup.select("td.result-snippet"):
            text = td.get_text(separator=" ", strip=True)
            if text:
                snippets.append(text)
            if len(snippets) >= SEARCH_MAX_RESULTS:
                break
        if snippets:
            return " | ".join(snippets)
    except Exception:
        pass
    return None

def _ddg_html_search(query):
    """Scrape DuckDuckGo HTML search page."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=_HEADERS, timeout=SEARCH_TIMEOUT
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        
        # Find result snippets
        for result in soup.select(".result"):
            snippet_elem = result.select_one(".result__snippet")
            title_elem = result.select_one(".result__title")
            if snippet_elem:
                snippet = snippet_elem.get_text(separator=" ", strip=True)
                title = title_elem.get_text(strip=True) if title_elem else ""
                if snippet:
                    results.append(f"{title}: {snippet}" if title else snippet)
            if len(results) >= SEARCH_MAX_RESULTS:
                break
        
        if results:
            return " | ".join(results)
    except Exception:
        pass
    return None

def search(query):
    """Search the web using multiple strategies with fallbacks."""
    query = query.strip()
    if not query:
        return "No search query provided."
    
    # Strategy 1: duckduckgo_search library (most reliable)
    result = _ddgs_search(query)
    if result:
        return result
    
    # Strategy 2: DDG Instant Answer
    result = _ddg_instant(query)
    if result:
        return result
    
    # Strategy 3: DDG Lite scrape
    result = _ddg_scrape(query)
    if result:
        return result
    
    # Strategy 4: DDG HTML search scrape
    result = _ddg_html_search(query)
    if result:
        return result
    
    return f"I searched for '{query}' but couldn't retrieve results. The search services may be temporarily unavailable."
