"""
Traffic Simulator — Playwright concurrent browser contexts with realistic human behavior.

# pip install: playwright
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from shared.logger import get_logger

log = get_logger("traffic_simulator")

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ...",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) ...",
]

_TARGET_SITES = [
    "https://www.google.com",
    "https://www.github.com",
    "https://www.wikipedia.org",
    "https://www.reddit.com",
]

_MAX_CONCURRENT_SESSIONS = 3


@dataclass
class UserBehaviorBucket:
    """Defines a sequence of human-like interactions."""
    site: str
    pages_to_visit: int = 2
    click_probability: float = 0.3
    scroll_probability: float = 0.7
    type_probability: float = 0.1
    session_duration_seconds: float = 30.0


class TrafficSimulator:
    """
    Spawns concurrent Playwright browser contexts with random user behavior.
    Used for load testing and generating realistic traffic patterns.
    """

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._contexts: List[BrowserContext] = []
        self._running = False
        self._playwright = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        log.info("traffic_simulator_started")

    async def stop(self) -> None:
        self._running = False
        for ctx in self._contexts:
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("traffic_simulator_stopped")

    async def simulate_session(self, bucket: UserBehaviorBucket) -> None:
        """Run a single user behavior session."""
        if not self._browser:
            raise RuntimeError("Simulator not started")

        user_agent = random.choice(_USER_AGENTS)
        context = await self._browser.new_context(
            user_agent=user_agent,
            viewport={"width": random.randint(1024, 1920), "height": random.randint(768, 1080)},
            locale=random.choice(["en-US", "en-GB", "de-DE"]),
        )
        self._contexts.append(context)

        try:
            page = await context.new_page()
            await page.goto(bucket.site, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(random.uniform(1.0, 3.0))

            end_time = asyncio.get_event_loop().time() + bucket.session_duration_seconds
            visited = 0

            while asyncio.get_event_loop().time() < end_time and visited < bucket.pages_to_visit:
                # Scroll
                if random.random() < bucket.scroll_probability:
                    await page.evaluate(f"window.scrollBy(0, {random.randint(100, 800)})")
                    await asyncio.sleep(random.uniform(0.5, 2.0))

                # Click links
                if random.random() < bucket.click_probability:
                    links = await page.query_selector_all("a[href]")
                    if links:
                        link = random.choice(links)
                        try:
                            href = await link.get_attribute("href")
                            if href and not href.startswith("#") and "javascript" not in href:
                                await link.click()
                                await asyncio.sleep(random.uniform(2.0, 4.0))
                                visited += 1
                        except Exception:
                            pass

                # Type in search fields
                if random.random() < bucket.type_probability:
                    search_input = await page.query_selector("input[type='text'], input[name='q']")
                    if search_input:
                        await search_input.click()
                        await search_input.type("hello world", delay=random.randint(30, 100))
                        await asyncio.sleep(random.uniform(1.0, 2.0))

                await asyncio.sleep(random.uniform(1.0, 3.0))

        except Exception as e:
            log.debug("session_error", site=bucket.site[:40], error=str(e))
        finally:
            try:
                await context.close()
                if context in self._contexts:
                    self._contexts.remove(context)
            except Exception:
                pass

    async def simulate_concurrent(self, count: int = 3, duration_seconds: float = 30.0) -> None:
        """Run multiple concurrent simulated user sessions."""
        sem = asyncio.Semaphore(_MAX_CONCURRENT_SESSIONS)

        async def _run_bucket(bucket: UserBehaviorBucket):
            async with sem:
                await self.simulate_session(bucket)

        tasks = []
        for i in range(count):
            bucket = UserBehaviorBucket(
                site=random.choice(_TARGET_SITES),
                pages_to_visit=random.randint(1, 3),
                click_probability=random.uniform(0.2, 0.6),
                scroll_probability=random.uniform(0.5, 0.9),
                session_duration_seconds=random.uniform(duration_seconds * 0.5, duration_seconds),
            )
            tasks.append(_run_bucket(bucket))
            await asyncio.sleep(random.uniform(0.5, 2.0))

        await asyncio.gather(*tasks, return_exceptions=True)


traffic_simulator = TrafficSimulator()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.traffic_simulator import traffic_simulator
# await traffic_simulator.start()
# await traffic_simulator.simulate_concurrent(count=3, duration_seconds=20)
# await traffic_simulator.stop()
# ---
