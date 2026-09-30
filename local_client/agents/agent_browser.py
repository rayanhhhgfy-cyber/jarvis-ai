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
from shared.learning_loop import learning_loop

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

        # Consult past lessons before acting
        try:
            relevant = learning_loop.query_lessons(task.title or "")
            if relevant:
                log.info(
                    "browser_agent_relevant_lessons",
                    count=len(relevant),
                    top_error=relevant[0].get("error_pattern", "")[:120],
                )
        except Exception:
            pass  # lesson lookup must never block task execution

        try:
            action = task.payload.get("action", "search")
            
            if action == "search" or action == "research":
                result_data = await self._perform_web_search(task)
            elif action == "scrape":
                result_data = await self._scrape_page(task)
            elif action == "screenshot":
                result_data = await self._capture_screenshot(task)
            elif action == "evaluate_js":
                result_data = await self._evaluate_javascript(task)
            elif action == "fill_form":
                result_data = await self._fill_form(task)
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
            try:
                learning_loop.remember_lesson(
                    task_description=task.title or action,
                    error_pattern=type(e).__name__,
                    root_cause=str(e)[:500],
                    solution="",
                    file_path="local_client/agents/agent_browser.py",
                    success=False,
                )
            except Exception:
                pass  # lesson recording must never mask the original failure
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _perform_web_search(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs a real web search query via DuckDuckGo.

        Prefers Playwright-driven html.duckduckgo.com when available, falls back
        to the repo's real WebSearchService (DuckDuckGo Lite over httpx).
        Raises instead of returning fabricated results.
        """
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

        # Real fallback: repo's WebSearchService (DuckDuckGo Lite, no browser needed)
        try:
            from backend.services.web_search_service import web_search_service
            results = await web_search_service.search(query, max_results=5)
            if results:
                return {
                    "search_query": query,
                    "results": [
                        f"{r.get('title', '')} — {r.get('snippet', '')} ({r.get('url', '')})"
                        for r in results
                    ],
                    "source": "DuckDuckGo Lite (WebSearchService)",
                }
        except Exception as e:
            log.error("web_search_service_failed", error=str(e))

        raise RuntimeError(
            "Web search is unavailable: Playwright is not installed and the "
            "DuckDuckGo fallback failed. Install playwright "
            "(pip install playwright && playwright install chromium) or check "
            "network connectivity, then retry."
        )

    async def _capture_screenshot(self, task: TaskDefinition) -> Dict[str, Any]:
        """Captures a screenshot of a specific URL."""
        url = task.payload.get("url")
        if not url:
            raise ValueError("url is required for screenshot action")

        if playwright_available:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url)
                shot_path = f"shared/screenshots/shot_{int(time.time())}.png"
                os.makedirs("shared/screenshots", exist_ok=True)
                await page.screenshot(path=shot_path)
                await browser.close()
                return {"screenshot_path": shot_path, "url": url}
        return {"error": "Playwright unavailable"}

    async def _evaluate_javascript(self, task: TaskDefinition) -> Dict[str, Any]:
        """Evaluates custom JS on a page."""
        url = task.payload.get("url")
        script = task.payload.get("script")
        if not url:
            raise ValueError("url is required for evaluate_js action")
        if not script:
            raise ValueError("script is required for evaluate_js action")
        if playwright_available:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url)
                res = await page.evaluate(script)
                await browser.close()
                return {"result": res}
        return {"error": "Playwright unavailable"}

    async def _fill_form(self, task: TaskDefinition) -> Dict[str, Any]:
        """Fills a form and submits it."""
        url = task.payload.get("url")
        fields = task.payload.get("fields", {})  # {selector: value}
        if not url:
            raise ValueError("url is required for fill_form action")
        if playwright_available:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url)
                for selector, value in fields.items():
                    await page.fill(selector, value)
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("networkidle")
                res_url = page.url
                await browser.close()
                return {"final_url": res_url, "status": "form_submitted"}
        return {"error": "Playwright unavailable"}

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
