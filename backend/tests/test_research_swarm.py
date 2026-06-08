# ====================================================================
# JARVIS OMEGA — Research Swarm Service Unit Tests
# ====================================================================
"""
Unit tests for the Research Swarm service (multi-agent web research campaign).
"""

import pytest
from unittest.mock import AsyncMock, patch
from backend.services.research_swarm import ResearchSwarm

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def swarm():
    return ResearchSwarm()

@pytest.mark.anyio
@patch("backend.services.research_swarm.llm_service")
@patch("backend.services.research_swarm.web_search_service")
async def test_run_swarm(mock_search, mock_llm, swarm):
    """Test full research swarm flow with mocked LLM queries and web search results."""
    # Mock LLM generating sub-queries
    mock_llm.get_response = AsyncMock(side_effect=[
        '["site:reddit.com Python 3.13", "Python 3.13 performance improvements"]', # sub-queries
        "# Deep Research Report: Python 3.13\n\n## Executive Summary\nHighly performant." # synthesized report
    ])
    
    # Mock search_web results
    mock_search.search_web = AsyncMock(return_value={
        "success": True,
        "results": [
            {"title": "Python 3.13 release", "snippet": "Python 3.13 is out with performance boosts.", "url": "https://python.org/3.13"},
            {"title": "Reddit thread", "snippet": "Discussing Python 3.13 features.", "url": "https://reddit.com/r/python"}
        ]
    })
    
    # Mock fetch_url results
    mock_search.fetch_url = AsyncMock(side_effect=lambda url, max_chars: {
        "success": True,
        "url": url,
        "content": f"Full content of {url} showing features."
    })
    
    result = await swarm.run_swarm(query="Python 3.13 features", num_agents=2)
    
    assert result["success"] is True
    assert "Executive Summary" in result["report"]
    assert len(result["sources"]) == 2
    assert result["sources"][0]["url"] == "https://python.org/3.13"
    assert result["sub_queries"] == ["site:reddit.com Python 3.13", "Python 3.13 performance improvements"]
    
    # Verify mock call counts
    assert mock_search.search_web.call_count == 2
    assert mock_search.fetch_url.call_count == 2
    assert mock_llm.get_response.call_count == 2
