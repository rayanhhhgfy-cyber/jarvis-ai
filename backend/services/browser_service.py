from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import time
from typing import Dict, Any

import aiohttp

from shared.logger import get_logger

log = get_logger("browser_service")

_SCRIPT = os.path.join(os.path.dirname(__file__), "pw_browser.py")
_PORT = 9223
_BASE = f"http://127.0.0.1:{_PORT}"

# Quick check — if playwright is not installed, skip Playwright entirely
# to avoid long timeouts.
_PLAYWRIGHT_AVAILABLE: bool | None = None


def _check_playwright_installed() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is not None:
        return _PLAYWRIGHT_AVAILABLE
    try:
        importlib.import_module("playwright")
        _PLAYWRIGHT_AVAILABLE = True
    except ImportError:
        _PLAYWRIGHT_AVAILABLE = False
        log.warning("playwright_not_installed_skipping_browser_service")
    return _PLAYWRIGHT_AVAILABLE


class BrowserService:
    """
    Full browser control via a background Playwright process.
    Manages a persistent Chromium window (visible) that JARVIS can
    navigate, click, type, and press keys on.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None

    async def _ensure_running(self):
        # Skip entire Playwright subprocess if playwright is not installed
        if not _check_playwright_installed():
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && python -m playwright install chromium")

        # First check if pw_browser is already running
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{_BASE}/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        log.info("pw_browser_already_running")
                        return
        except Exception:
            pass

        if self._proc and self._proc.poll() is None:
            return

        self._proc = await asyncio.create_subprocess_exec(
            "python", _SCRIPT, str(_PORT),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # Wait for the Flask server to start
        for _ in range(20):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"{_BASE}/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                        if r.status == 200:
                            log.info("pw_browser_ready")
                            return
            except Exception:
                pass
            await asyncio.sleep(0.5)
        raise RuntimeError("pw_browser did not start in time")

    async def _post(self, path: str, data: dict | None = None) -> dict:
        await self._ensure_running()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{_BASE}{path}",
                    json=data or {},
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as r:
                    try:
                        return await r.json()
                    except Exception:
                        text = await r.text()
                        return {"success": False, "error": f"Non-JSON response ({r.status}): {text[:200]}"}
        except Exception as e:
            return {"success": False, "error": f"browser_service._post failed: {e}"}

    async def navigate(self, url: str, timeout: int = 30000) -> Dict[str, Any]:
        """Open URL in the persistent Playwright browser."""
        try:
            return await self._post("/navigate", {"url": url, "timeout": timeout})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def interact(self, url: str, actions: list, timeout: int = 30000) -> Dict[str, Any]:
        """Open URL in the Playwright browser and perform actions."""
        try:
            return await self._post("/interact", {"url": url, "actions": actions, "timeout": timeout})
        except Exception as e:
            log.error("interact_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def execute_js(self, script: str) -> Dict[str, Any]:
        try:
            return await self._post("/js", {"script": script})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_text(self, selector: str) -> Dict[str, Any]:
        try:
            return await self._post("/text", {"selector": selector})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def click(self, selector: str) -> Dict[str, Any]:
        try:
            return await self._post("/click", {"selector": selector})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def type_text(self, selector: str, text: str) -> Dict[str, Any]:
        try:
            return await self._post("/type", {"selector": selector, "text": text})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def press_key(self, key: str) -> Dict[str, Any]:
        try:
            return await self._post("/press", {"key": key})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_page_info(self) -> Dict[str, Any]:
        """Returns current page URL, title, and whether a login form is detected."""
        try:
            return await self._post("/info")
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def screenshot(self) -> Dict[str, Any]:
        try:
            return await self._post("/screenshot")
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def instagram_dm(self, username: str, message: str) -> Dict[str, Any]:
        """Open Instagram DM inbox, find user (or use first thread), send message."""
        try:
            return await self._post("/instagram_dm", {"username": username, "message": message})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def instagram_read_inbox(self) -> Dict[str, Any]:
        """Return list of DM conversation names visible in Instagram inbox."""
        try:
            return await self._post("/instagram_read_inbox", {})
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self) -> None:
        if self._proc:
            try:
                async with aiohttp.ClientSession() as s:
                    await s.post(f"{_BASE}/close", timeout=aiohttp.ClientTimeout(total=5))
            except Exception:
                pass
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        log.info("browser_closed")


browser_service = BrowserService()
