"""
Lazarus Sentry — self-resurrection daemon.
Polls /health every 30s. After 3 consecutive failures, restarts the server.

# pip install: httpx
# TERMUX-NOTE: Android may kill background processes. Use termux-wake-lock.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime
from typing import Optional

import httpx

from shared.logger import get_logger

log = get_logger("lazarus_sentry")

_HEALTH_URL = "http://127.0.0.1:8000/health"
_POLL_INTERVAL = 30
_MAX_FAILURES = 3


class LazarusSentry:
    """
    Detached watchdog that monitors the backend health endpoint.
    On 3 consecutive failures, executes subprocess.Popen to restart.
    Announce resurrection via sound.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._failure_count = 0
        self._http = httpx.AsyncClient(timeout=10.0)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        log.info("lazarus_sentry_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._http.aclose()
        log.info("lazarus_sentry_stopped")

    async def _watchdog_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_POLL_INTERVAL)
            try:
                resp = await self._http.get(_HEALTH_URL)
                if resp.status_code == 200:
                    self._failure_count = 0
                    continue
            except Exception:
                pass

            self._failure_count += 1
            log.warning("lazarus_health_check_failed", count=self._failure_count, max=_MAX_FAILURES)

            if self._failure_count >= _MAX_FAILURES:
                await self._resurrect()
                self._failure_count = 0
                # Wait before re-checking
                await asyncio.sleep(10)

    async def _resurrect(self) -> None:
        """Restart the backend server process."""
        log.critical("lazarus_triggered", message="Initiating self-resurrection protocol")

        try:
            from backend.services.sound_engine import sound_engine, JarvisEvent
            await sound_engine.jarvis_alert(JarvisEvent.LAZARUS_TRIGGERED)
        except Exception:
            pass

        try:
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("lazarus_resurrection_command_executed")
        except Exception as e:
            log.error("lazarus_resurrection_failed", error=str(e))


lazarus_sentry = LazarusSentry()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.lazarus_sentry import lazarus_sentry
# await lazarus_sentry.start()
# # ... server runs ...
# await lazarus_sentry.stop()
# ---
