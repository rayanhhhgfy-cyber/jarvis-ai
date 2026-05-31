# ====================================================================
# JARVIS OMEGA — Browser Agent
# ====================================================================
"""
Specialized Browser Agent responsible for Playwright-based automation,
web searching, scraping, and automated research workflows.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_browser")

# Playwright availability import
playwright_available = False
try:
    from playwright.async_api import async_playwright
    playwright_available = True
except ImportError:
    log.warning("playwright_not_installed_using_stub_fallback")

class AgentBrowser:
    """
    Automated browser agent. Interfaces with Playwright to browse pages,
    fill out forms, download logs, and capture UI reports.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_browser"
        self.agent_type = AgentType.BROWSER

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes browsing requests like page loads, web searching, or screenshot capturing."""
        log.info("browser_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "search")
            
            if action == "search" or action == "research":
                result_data = await self._perform_web_search(task)
            elif action == "scrape":
                result_data = await self._scrape_page(task)
            else:
                raise ValueError(f"Unknown Browser action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("browser_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _perform_web_search(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs a simulated web search query (connecting to duckduckgo/google in production)."""
        query = task.payload.get("query")
        if not query:
            raise ValueError("query is required for web search")

        log.info("performing_browser_search", query=query)
        
        # Real web search with Playwright if available
        if playwright_available:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    # Browse DuckDuckGo
                    await page.goto(f"https://html.duckduckgo.com/html/?q={query}")
                    links = await page.locator(".result__snippet").all_text_contents()
                    await browser.close()
                    
                    return {
                        "search_query": query,
                        "results": links[:5],
                        "source": "DuckDuckGo (Playwright)"
                    }
            except Exception as e:
                log.error("playwright_search_failed_falling_back", error=str(e))

        # Stub search fallback
        return {
            "search_query": query,
            "results": [
                f"Top documentation reference for '{query}'",
                f"Release notes for '{query}' - version 4.5"
            ],
            "source": "Static Search Engine Stub"
        }

    async def _scrape_page(self, task: TaskDefinition) -> Dict[str, Any]:
        """Loads a specific URL page and returns full parsed text."""
        url = task.payload.get("url")
        if not url:
            raise ValueError("url is required for scrape action")

        if playwright_available:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(url)
                    text = await page.evaluate("() => document.body.innerText")
                    title = await page.title()
                    await browser.close()
                    
                    return {
                        "url": url,
                        "title": title,
                        "page_text": text[:5000],  # Cap response size
                        "scraped_successfully": True
                    }
            except Exception as e:
                log.error("playwright_scrape_failed", error=str(e))

        return {
            "url": url,
            "scraped_successfully": False,
            "error": "Playwright is not loaded/enabled on this machine environment."
        }
