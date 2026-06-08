"""
DB Heartbeat — Supabase REST health checks, latency logging, fallback.

# TERMUX-NOTE: Stubs when SUPABASE_URL / SUPABASE_API_KEY absent from .env.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from shared.logger import get_logger

log = get_logger("db_heartbeat")

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_API_KEY", "")
_CHECK_INTERVAL = 60


class DBHeartbeat:
    """
    Periodic Supabase health check. Falls back gracefully when credentials missing.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._enabled = bool(_SUPABASE_URL and _SUPABASE_KEY)

    async def start(self) -> None:
        if self._running:
            return
        if not self._enabled:
            log.info("db_heartbeat_disabled — no Supabase credentials")
            return
        self._running = True
        self._http = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._heartbeat_loop())
        log.info("db_heartbeat_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
        log.info("db_heartbeat_stopped")

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await self._check()
            await asyncio.sleep(_CHECK_INTERVAL)

    async def _check(self) -> None:
        if not self._http or not self._enabled:
            return
        try:
            start = datetime.utcnow()
            resp = await self._http.get(
                f"{_SUPABASE_URL}/rest/v1/",
                headers={"apikey": _SUPABASE_KEY},
            )
            latency = (datetime.utcnow() - start).total_seconds() * 1000
            status = "ok" if resp.status_code < 400 else "degraded"
            log.info("db_heartbeat_check", status=status, latency_ms=round(latency, 1))
        except httpx.HTTPError as e:
            log.warning("db_heartbeat_failed", error=str(e))


db_heartbeat = DBHeartbeat()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.db_heartbeat import db_heartbeat
# await db_heartbeat.start()
# await db_heartbeat.stop()
# ---
