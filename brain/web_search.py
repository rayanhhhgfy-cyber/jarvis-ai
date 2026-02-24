import os
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
try:
    from googlesearch import search as gsearch
except ImportError:
    gsearch = None
try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

# Try to get API key from config
try:
    from config import TAVILY_API_KEY
except ImportError:
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

def search(q):
    q = q.strip()
    if not q:
        return "No search query provided."

    # 1. Try Tavily if API key is available
    if TAVILY_API_KEY and TavilyClient:
        try:
            tavily = TavilyClient(api_key=TAVILY_API_KEY)
            response = tavily.search(query=q, search_depth="basic")
            results = response.get('results', [])
            if results:
                formatted_results = []
                for res in results[:5]:
                    formatted_results.append(f"Source: {res['url']}\nContent: {res['content']}\n")
                return "\n".join(formatted_results)
        except Exception as e:
            print(f"Tavily Search Error: {e}")

    # 2. Try duckduckgo-search with region enforcement
    try:
        with DDGS() as ddgs:
            # Forcing region and moderate safesearch
            # Appending lang:en to the query string for extra enforcement
            en_q = f"{q} lang:en"
            results = list(ddgs.text(en_q, region='us-en', max_results=5))
            if results and any(res.get('body') for res in results):
                formatted_results = []
                for res in results:
                    formatted_results.append(f"Title: {res['title']}\nURL: {res['href']}\nBody: {res['body']}\n")
                return "\n".join(formatted_results)
    except Exception as e:
        print(f"DuckDuckGo Search Error: {e}")

    # 3. Fallback to googlesearch-python if DDG fails or is irrelevant
    if gsearch:
        try:
            results = list(gsearch(q, num_results=5, lang="en"))
            if results:
                formatted_results = []
                for url in results:
                    formatted_results.append(f"URL: {url}\n(Google fallback result)\n")
                return "\n".join(formatted_results)
        except Exception as e:
            print(f"Google Search Error: {e}")

    return f"Could not find relevant results for '{q}'."

def get_url_content(url):
    """Fetches the text content of a URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
            
        return soup.get_text(separator=' ', strip=True)[:2000]
    except Exception as e:
        return f"Error fetching {url}: {str(e)}"
