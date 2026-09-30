# ====================================================================
# JARVIS OMEGA — Proactive Watcher Service
# ====================================================================
"""
Background service that monitors the world and Sir's environment.
Triggers JARVIS to act proactively without being asked.

Ported from the self-evolving-intelligence branch and repaired:
- dead imports removed
- alerts go through main's broadcast_to_ui (no branch-only ui_manager)
- fabricated "empire metrics" cycle deleted (it broadcast made-up numbers)
- news alerts only fire when the brief actually changes (hash check)
- morning briefing fires once per day, not on a fragile modulo check
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone

from backend.services.llm_service import llm_service
from backend.services.web_search_service import web_search_service
from shared.logger import get_logger

log = get_logger("proactive_watcher")


class ProactiveWatcher:
    def __init__(self):
        self._running = False
        self._last_market_check = 0.0
        self._last_news_check = 0.0
        self._last_news_hash = ""
        self._last_morning_brief_date = ""

    async def start(self):
        self._running = True
        log.info("proactive_watcher_started")
        asyncio.create_task(self._watch_loop())

    async def stop(self):
        self._running = False
        log.info("proactive_watcher_stopped")

    async def _watch_loop(self):
        while self._running:
            try:
                now = time.time()

                # 1. Market Monitoring (every 15 mins)
                if now - self._last_market_check > 900:
                    await self._check_markets()
                    self._last_market_check = now

                # 2. News & Trends Monitoring (every 1 hour)
                if now - self._last_news_check > 3600:
                    await self._check_breaking_news()
                    self._last_news_check = now

                # 3. Time-based Proactivity (morning briefing)
                await self._check_schedule_proactivity()

                await asyncio.sleep(60)  # Pulse every minute
            except Exception as e:
                log.error("watcher_loop_error", error=str(e))
                await asyncio.sleep(10)

    async def _check_markets(self):
        log.info("proactive_market_check")
        # Search for major anomalies
        news = await web_search_service.search_and_summarize(
            "major stock market crypto moves last hour"
        )
        if "crash" in news.lower() or "surge" in news.lower() or "breaking" in news.lower():
            analysis = await llm_service.get_response(
                f"Analyze this market context and decide if Sir needs an urgent alert: {news}",
                system_instructions=(
                    "You are the OMEGA Risk Monitor. Only alert if there is a "
                    "million-dollar margin impact. Start your response with the "
                    "word ALERT if, and only if, an urgent alert is warranted."
                ),
            )
            if "ALERT" in analysis.upper():
                await self._trigger_alert("Market Intelligence", analysis)

    async def _check_breaking_news(self):
        log.info("proactive_news_check")
        news = await web_search_service.search_and_summarize(
            "breaking tech and AI news for today"
        )
        brief = await llm_service.get_response(
            f"Summarize this for Sir: {news}",
            system_instructions=(
                "You are JARVIS. Provide a concise, high-level summary of how "
                "this impacts the mission."
            ),
        )
        # Only alert when the brief actually changed since last time.
        digest = hashlib.sha256(brief.encode("utf-8")).hexdigest()
        if digest != self._last_news_hash:
            self._last_news_hash = digest
            await self._trigger_alert("Global Tech Pulse", brief)
        else:
            log.info("proactive_news_unchanged_skipping_alert")

    async def _check_schedule_proactivity(self):
        now = datetime.now(timezone.utc)
        # Morning briefing: once per day, at/after 08:00 local server time.
        today = now.date().isoformat()
        if now.hour >= 8 and self._last_morning_brief_date != today:
            self._last_morning_brief_date = today
            await self._trigger_alert(
                "Morning Strategic Briefing",
                "Systems nominal. I have prepared your mission plan for today, Sir.",
            )

    async def _trigger_alert(self, title: str, content: str):
        log.info("proactive_trigger", title=title)
        # Lazy import to avoid a circular import with backend.main.
        from backend.main import broadcast_to_ui

        await broadcast_to_ui(
            {
                "type": "proactive_report",
                "payload": {
                    "title": title,
                    "report": content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }
        )


proactive_watcher = ProactiveWatcher()
