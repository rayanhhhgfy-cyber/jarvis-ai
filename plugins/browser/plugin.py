# ====================================================================
# JARVIS OMEGA — Browser Plugin (Playwright, headless)
# ====================================================================
"""
Phase 10 plugin: free browser automation via Playwright.

Launches a single shared chromium instance (headless) on first tool use and
keeps it alive for the rest of the process. Tools accept standard CSS
selectors and operate on the current page.

Risk-tier policy:
  - Tier 0 (observe): navigate, extract, screenshot, wait_for, back, forward
  - Tier 2 (system):  click, type   (because they trigger server-side effects)

Playwright is already in requirements.txt. The plugin degrades gracefully if
the browser binaries are not installed (``playwright install chromium`` not
yet run).
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Shared browser state (process-wide singleton)
# --------------------------------------------------------------------

_pw_lock = asyncio.Lock()
_pw_instance = None       # lazy playwright root
_browser = None           # shared chromium browser
_context = None           # shared browsing context (cookies persist within session)
_page = None              # current page


async def _ensure_browser() -> Any:
    """Lazily start Playwright + chromium. Returns the current page object."""
    global _pw_instance, _browser, _context, _page

    if _page is not None:
        return _page

    async with _pw_lock:
        if _page is not None:
            return _page
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "playwright is not installed. Add to requirements.txt and run "
                "`playwright install chromium` to download the browser binary."
            ) from e

        _pw_instance = await async_playwright().start()
        try:
            _browser = await _pw_instance.chromium.launch(headless=True)
        except Exception as e:
            raise RuntimeError(
                f"Failed to launch chromium. Run `playwright install chromium`. "
                f"Underlying error: {e}"
            ) from e

        _context = await _browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        _page = await _context.new_page()
    return _page


async def _close_browser() -> None:
    """Tear down the shared browser (used by tests)."""
    global _pw_instance, _browser, _context, _page
    if _context:
        try:
            await _context.close()
        except Exception:
            pass
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
    if _pw_instance:
        try:
            await _pw_instance.stop()
        except Exception:
            pass
    _pw_instance = _browser = _context = _page = None


# --------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------

@tool(
    name="browser.navigate",
    description="Navigate the shared browser to a URL. Returns the final URL after redirects and the page title.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute URL including scheme (https://...)."},
            "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "default": "load"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
        "required": ["url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_navigate(url: str, wait_until: str = "load", timeout_ms: int = 30000) -> Dict[str, Any]:
    try:
        page = await _ensure_browser()
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}
    try:
        resp = await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        status = resp.status if resp else None
        return {
            "ok": True,
            "url": page.url,
            "title": await page.title(),
            "status": status,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


@tool(
    name="browser.click",
    description="Click an element matching a CSS selector.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector (e.g. 'button#submit', 'a[href=\"/login\"]')."},
            "timeout_ms": {"type": "integer", "default": 5000},
        },
        "required": ["selector"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="browser",
)
async def browser_click(selector: str, timeout_ms: int = 5000) -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        await page.click(selector, timeout=timeout_ms)
        return {"ok": True, "clicked": selector}
    except Exception as e:
        return {"ok": False, "error": str(e), "selector": selector}


@tool(
    name="browser.type",
    description="Type text into an input matching a CSS selector. Optionally press Enter afterwards.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "press_enter": {"type": "boolean", "default": False},
            "delay_ms": {"type": "integer", "default": 0, "description": "Per-keypress delay for realism."},
        },
        "required": ["selector", "text"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="browser",
)
async def browser_type(selector: str, text: str, press_enter: bool = False, delay_ms: int = 0) -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        await page.fill(selector, text)
        if delay_ms:
            # Slow typewriter for sites that detect instant fills.
            await page.press(selector, "Control+a")
            await page.type(selector, text, delay=delay_ms)
        if press_enter:
            await page.press(selector, "Enter")
        return {"ok": True, "selector": selector, "chars_typed": len(text)}
    except Exception as e:
        return {"ok": False, "error": str(e), "selector": selector}


@tool(
    name="browser.extract",
    description="Extract content from elements matching a CSS selector. Returns a list of strings (text or attribute values).",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "default": "body"},
            "attribute": {"type": "string", "default": "text", "description": "'text' for visible text, or an attribute name like 'href'."},
            "limit": {"type": "integer", "default": 100},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_extract(selector: str = "body", attribute: str = "text", limit: int = 100) -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        if attribute == "text":
            results = await page.eval_on_selector_all(
                selector,
                "(els) => els.map(e => e.innerText)",
            )
        else:
            results = await page.eval_on_selector_all(
                selector,
                "(els, attr) => els.map(e => e.getAttribute(attr))",
                attribute,
            )
        cleaned = [r for r in results if r]
        return {
            "ok": True,
            "selector": selector,
            "attribute": attribute,
            "count": len(cleaned),
            "items": cleaned[:limit],
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "selector": selector}


@tool(
    name="browser.screenshot",
    description="Capture a PNG screenshot of the current page. Returns base64-encoded image.",
    parameters={
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "default": True},
            "selector": {"type": "string", "description": "Optional CSS selector to screenshot just that element."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_screenshot(full_page: bool = True, selector: str = "") -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        if selector:
            element = await page.query_selector(selector)
            if not element:
                return {"ok": False, "error": f"selector not found: {selector}"}
            img_bytes = await element.screenshot()
        else:
            img_bytes = await page.screenshot(full_page=full_page)
        return {
            "ok": True,
            "image_base64": base64.b64encode(img_bytes).decode("ascii"),
            "bytes": len(img_bytes),
            "format": "png",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="browser.wait_for",
    description="Wait until an element matching a CSS selector is present on the page.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 5000},
            "state": {"type": "string", "enum": ["attached", "detached", "visible", "hidden"], "default": "visible"},
        },
        "required": ["selector"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_wait_for(selector: str, timeout_ms: int = 5000, state: str = "visible") -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        await page.wait_for_selector(selector, state=state, timeout=timeout_ms)
        return {"ok": True, "selector": selector, "state": state}
    except Exception as e:
        return {"ok": False, "error": str(e), "selector": selector}


@tool(
    name="browser.back",
    description="Navigate the browser back one page in history.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_back() -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        response = await page.go_back()
        return {"ok": True, "url": page.url, "had_response": response is not None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="browser.forward",
    description="Navigate the browser forward one page in history.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_forward() -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        response = await page.go_forward()
        return {"ok": True, "url": page.url, "had_response": response is not None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="browser.scroll",
    description="Scroll the page by a number of pixels (positive = down, negative = up).",
    parameters={
        "type": "object",
        "properties": {
            "delta_y": {"type": "integer", "default": 500},
            "delta_x": {"type": "integer", "default": 0},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_scroll(delta_y: int = 500, delta_x: int = 0) -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        await page.mouse.wheel(delta_x, delta_y)
        return {"ok": True, "scrolled_y": delta_y, "scrolled_x": delta_x}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="browser.eval",
    description="Evaluate a JavaScript expression on the current page and return the result.",
    parameters={
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "JavaScript to evaluate. Must return a JSON-serializable value."},
        },
        "required": ["script"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="browser",
)
async def browser_eval(script: str) -> Dict[str, Any]:
    page = await _ensure_browser()
    try:
        result = await page.evaluate(script)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="browser.cookies",
    description="Return all cookies currently stored in the shared browser context.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="browser",
)
async def browser_cookies() -> Dict[str, Any]:
    global _context
    if _context is None:
        return {"ok": True, "cookies": []}
    try:
        cookies = await _context.cookies()
        # Redact actual values — cookies are sensitive even in observe tier.
        safe = [
            {"name": c.get("name"), "domain": c.get("domain"), "path": c.get("path"),
             "expires": c.get("expires"), "secure": c.get("secure"),
             "value_len": len(str(c.get("value", "")))}
            for c in cookies
        ]
        return {"ok": True, "cookies": safe, "count": len(safe)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "browser"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Playwright-based headless browser automation (navigate, click, type, extract, screenshot)."
