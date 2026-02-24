# =============================================================================
# brain/web_search.py — Free web search via DuckDuckGo (no API key)
# Strategy 1: DDG Instant Answer API (JSON)
# Strategy 2: DDG Lite HTML scrape
# =============================================================================

import requests
from bs4 import BeautifulSoup
from config import SEARCH_MAX_RESULTS, SEARCH_TIMEOUT

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def _ddg_instant(query):
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
            source = data.get("AbstractSource") or ""
            return answer + (f" (Source: {source})" if source else "")
    except Exception:
        pass
    return None

def _ddg_scrape(query):
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

def search(query):
    query = query.strip()
    if not query:
        return "No search query provided."
    result = _ddg_instant(query)
    if result:
        return result
    result = _ddg_scrape(query)
    if result:
        return result
    return f"I searched for '{query}' but couldn't retrieve results. Check your internet connection."
