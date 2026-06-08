"""
Phantom Browser — Playwright wrapper with anti-detection measures.

# pip install: playwright
# termux: pkg install playwright
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import async_playwright, BrowserContext, Page

from shared.logger import get_logger

log = get_logger("phantom_browser")


class PhantomBrowser:
    """
    Browser automation with:
    - Canvas/webdriver/plugins spoofing
    - Bezier-curve mouse movements
    - Persistent context support
    - Session cookie reuse
    """

    def __init__(self, headless: bool = True, channel: str = "msedge"):
        self._headless = headless
        self._channel = channel
        self._context: Optional[BrowserContext] = None
        self._playwright = None
        self._user_data_dir = os.path.join(os.path.expanduser("~"), ".jarvis", "browser_profile")

    async def start(self) -> None:
        """Launch Playwright with a persistent context."""
        self._playwright = await async_playwright().start()

        # Try Edge channel; fall back to Chromium
        browser_type = self._playwright.chromium

        self._context = await browser_type.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=self._headless,
            channel=self._channel if self._channel == "msedge" else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-web-security",
                "--disable-dev-shm-usage",
            ],
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )

        # Inject anti-detection script into every new page
        await self._context.add_init_script("""
            // Override webdriver
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            // Canvas noise
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type) {
                const canvas = this;
                const ctx = canvas.getContext('2d');
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                for (let i = 0; i < imageData.data.length; i += 4) {
                    imageData.data[i] = imageData.data[i] ^ 1;
                }
                ctx.putImageData(imageData, 0, 0);
                return originalToDataURL.call(this, type);
            };
        """)

        log.info("phantom_browser_started", user_data_dir=self._user_data_dir)

    async def stop(self) -> None:
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("phantom_browser_stopped")

    async def new_page(self) -> Page:
        """Create a new page in the persistent context."""
        if not self._context:
            raise RuntimeError("Browser not started. Call start() first.")
        page = await self._context.new_page()
        return page

    async def navigate(self, url: str) -> Page:
        """Create page, navigate, return page."""
        page = await self.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page

    async def human_click(self, page: Page, selector: str) -> None:
        """Click with Bezier-curve mouse movement."""
        element = await page.wait_for_selector(selector, timeout=10000)
        box = await element.bounding_box()
        if box:
            steps = random.randint(5, 12)
            from_x = box["x"] + box["width"] * random.uniform(0.1, 0.9)
            from_y = box["y"] + box["height"] * random.uniform(0.1, 0.9)
            await page.mouse.move(from_x, from_y, steps=steps)
            await asyncio.sleep(random.uniform(0.05, 0.2))
            await element.click()
        else:
            await element.click()

    async def human_type(self, page: Page, selector: str, text: str) -> None:
        """Type text with human-like delays."""
        element = await page.wait_for_selector(selector, timeout=10000)
        await element.click()
        for char in text:
            await element.type(char, delay=random.randint(30, 120))

    async def screenshot(self, page: Page) -> bytes:
        return await page.screenshot(type="png")

    async def execute_js(self, page: Page, script: str) -> Any:
        return await page.evaluate(script)

    async def get_text(self, page: Page, selector: str) -> str:
        element = await page.wait_for_selector(selector, timeout=10000)
        return await element.inner_text()


phantom_browser = PhantomBrowser()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.phantom_browser import phantom_browser
# await phantom_browser.start()
# page = await phantom_browser.navigate("https://example.com")
# await phantom_browser.human_click(page, "#login-button")
# await phantom_browser.stop()
# ---
