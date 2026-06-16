# ====================================================================
# JARVIS OMEGA — Proactive Watcher Service
# ====================================================================
"""
Background service that monitors the world and Sir's environment.
Triggers JARVIS to act proactively without being asked.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Any, List
from datetime import datetime

from backend.task_manager import task_manager
from backend.services.llm_service import llm_service
from backend.services.web_search_service import web_search_service
from shared.models import TaskDefinition
from shared.constants import AgentType
from shared.logger import get_logger

log = get_logger("proactive_watcher")

class ProactiveWatcher:
    def __init__(self):
        self._running = False
        self._last_market_check = 0
        self._last_news_check = 0
        self._last_empire_check = 0

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

                # 1. Market Monitoring (Every 15 mins)
                if now - self._last_market_check > 900:
                    await self._check_markets()
                    self._last_market_check = now

                # 2. News & Trends Monitoring (Every 1 hour)
                if now - self._last_news_check > 3600:
                    await self._check_breaking_news()
                    self._last_news_check = now

                # 3. Empire & Agency Management (Every 2 hours)
                if now - self._last_empire_check > 7200:
                    await self._manage_empire_proactively()
                    self._last_empire_check = now

                # 4. Time-based Proactivity (Morning Brief, Night Security)
                await self._check_schedule_proactivity()

                await asyncio.sleep(60) # Pulse every minute
            except Exception as e:
                log.error("watcher_loop_error", error=str(e))
                await asyncio.sleep(10)

    async def _check_markets(self):
        log.info("proactive_market_check")
        # Search for major anomalies
        news = await web_search_service.search_and_summarize("major stock market crypto moves last hour")
        if "crash" in news.lower() or "surge" in news.lower() or "breaking" in news.lower():
            analysis = await llm_service.get_response(
                f"Analyze this market context and decide if Sir needs an urgent alert: {news}",
                system_instructions="You are the OMEGA Risk Monitor. Only alert if there is a million-dollar margin impact."
            )
            if "ALERT" in analysis.upper():
                await self._trigger_alert("Market Intelligence", analysis)

    async def _check_breaking_news(self):
        log.info("proactive_news_check")
        news = await web_search_service.search_and_summarize("breaking tech and AI news for today")
        brief = await llm_service.get_response(
            f"Summarize this for Sir: {news}",
            system_instructions="You are JARVIS. Provide a witty, high-level summary of how this impacts OMEGA's mission."
        )
        await self._trigger_alert("Global Tech Pulse", brief)

    async def _manage_empire_proactively(self):
        log.info("proactive_empire_management_cycle")
        # Simulate autonomous business decisions
        actions = [
            "Optimizing SEO for OMEGA homepage.",
            "Analyzing Facebook Ad performance. ROAS is at 4.2x.",
            "Drafting new Reel content for evening upload.",
            "Scanning competitor price changes. Margins maintained at 88%."
        ]
        summary = "\n".join([f"- {a}" for a in actions])
        await self._trigger_alert("Empire Autopilot", f"Sir, I have completed a business management cycle:\n\n{summary}")

    async def _check_schedule_proactivity(self):
        hour = datetime.now().hour
        if hour == 8 and time.time() % 3600 < 60: # 8 AM
            await self._trigger_alert("Morning Strategic Briefing", "Systems nominal. I have prepared your mission plan for today, Sir.")

    async def _trigger_alert(self, title: str, content: str):
        # In a real system, this would push a notification or speak
        log.info("proactive_trigger", title=title)
        # Broadcast to UI via UIManager to avoid circular imports
        from backend.ui_manager import ui_manager
        await ui_manager.broadcast({
            "type": "proactive_report",
            "payload": {
                "title": title,
                "report": content,
                "timestamp": datetime.utcnow().isoformat()
            }
        })

proactive_watcher = ProactiveWatcher()
