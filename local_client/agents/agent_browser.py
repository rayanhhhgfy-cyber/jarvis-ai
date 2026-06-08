from __future__ import annotations

import os
import time
import base64
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_browser")

playwright_available = False
try:
    from playwright.async_api import async_playwright
    playwright_available = True
except ImportError:
    log.warning("playwright_not_installed_using_stub_fallback")


class AgentBrowser:

    def __init__(self) -> None:
        self.agent_id = "agent_browser"
        self.agent_type = AgentType.BROWSER

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("browser_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "search")
            if action in ("search", "research"):
                result_data = await self._perform_web_search(task)
            elif action == "scrape":
                result_data = await self._scrape_page(task)
            elif action == "navigate":
                result_data = await self._navigate_and_interact(task)
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
        query = task.payload.get("query")
        if not query:
            raise ValueError("query is required for web search")

        log.info("performing_browser_search", query=query)

        if playwright_available:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(f"https://html.duckduckgo.com/html/?q={query}", timeout=30000)
                    await page.wait_for_timeout(2000)

                    captcha_detected = await self._check_captcha(page)
                    if captcha_detected:
                        log.warning("captcha_detected_during_search")
                        solved = await self._solve_captcha_on_page(page)
                        if solved:
                            await page.wait_for_timeout(2000)

                    snippets = await page.locator(".result__snippet").all_text_contents()
                    titles = await page.locator(".result__title").all_text_contents()
                    links = await page.locator(".result__url").all_text_contents()

                    results = []
                    for i in range(min(len(snippets), 5)):
                        results.append({
                            "title": titles[i] if i < len(titles) else "",
                            "snippet": snippets[i],
                            "url": links[i] if i < len(links) else "",
                        })

                    await browser.close()
                    return {"search_query": query, "results": results, "source": "DuckDuckGo (Playwright)"}
            except Exception as e:
                log.error("playwright_search_failed", error=str(e))

        return {
            "search_query": query,
            "results": [{"title": f"Results for '{query}'", "snippet": "Search unavailable without Playwright.", "url": ""}],
            "source": "Fallback",
        }

    async def _scrape_page(self, task: TaskDefinition) -> Dict[str, Any]:
        url = task.payload.get("url")
        if not url:
            raise ValueError("url is required for scrape action")

        if playwright_available:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(url, timeout=30000)
                    await page.wait_for_timeout(3000)

                    captcha_detected = await self._check_captcha(page)
                    if captcha_detected:
                        await self._solve_captcha_on_page(page)
                        await page.wait_for_timeout(2000)

                    text = await page.evaluate("() => document.body.innerText")
                    title = await page.title()
                    screenshot_bytes = await page.screenshot(full_page=True)
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

                    await browser.close()
                    return {
                        "url": url,
                        "title": title,
                        "page_text": text[:10000],
                        "screenshot_base64": screenshot_b64,
                        "scraped_successfully": True,
                    }
            except Exception as e:
                log.error("playwright_scrape_failed", error=str(e))

        return {"url": url, "scraped_successfully": False, "error": "Playwright not available"}

    async def _navigate_and_interact(self, task: TaskDefinition) -> Dict[str, Any]:
        url = task.payload.get("url")
        actions = task.payload.get("actions", [])
        if not url:
            raise ValueError("url is required")

        if not playwright_available:
            return {"navigated": False, "error": "Playwright not available"}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(url, timeout=30000)

            captcha_detected = await self._check_captcha(page)
            if captcha_detected:
                await self._solve_captcha_on_page(page)

            for action in actions:
                act_type = action.get("type")
                selector = action.get("selector")
                value = action.get("value")
                if act_type == "click" and selector:
                    await page.click(selector)
                    await page.wait_for_timeout(1000)
                elif act_type == "fill" and selector and value:
                    await page.fill(selector, value)
                    await page.wait_for_timeout(500)
                elif act_type == "wait":
                    await page.wait_for_timeout(int(value or 2000))

            final_text = await page.evaluate("() => document.body.innerText")
            final_url = page.url
            await browser.close()

            return {"navigated": True, "final_url": final_url, "page_text": final_text[:5000]}

    async def _check_captcha(self, page) -> bool:
        try:
            captcha_selectors = [
                "iframe[src*='recaptcha']",
                "iframe[src*='captcha']",
                "div[class*='captcha']",
                "img[alt*='captcha']",
                "input[name*='captcha']",
                "#captcha",
                ".captcha",
            ]
            for sel in captcha_selectors:
                el = await page.query_selector(sel)
                if el:
                    return True
            return False
        except Exception:
            return False

    async def _solve_captcha_on_page(self, page) -> bool:
        try:
            screenshot_bytes = await page.screenshot()
            from backend.vision.captcha_solver import captcha_solver
            solution = await captcha_solver.solve(screenshot_bytes)
            if solution.get("type") == "TEXT" and solution.get("solution"):
                input_sel = await page.query_selector("input[name*='captcha'], input#captcha, input[placeholder*='captcha']")
                if input_sel:
                    await input_sel.fill(solution["solution"])
                    submit_btn = await page.query_selector("button[type='submit'], input[type='submit']")
                    if submit_btn:
                        await submit_btn.click()
                    return True
            return False
        except Exception as e:
            log.error("captcha_solve_page_failed", error=str(e))
            return False
