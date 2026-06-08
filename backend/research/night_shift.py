from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from shared.logger import get_logger
from backend.services.llm_service import llm_service
from backend.services.web_search_service import web_search_service
from backend.scheduler import scheduler

log = get_logger("night_shift")

TOPICS = [
    "latest AI and machine learning breakthroughs this week",
    "new software engineering tools and frameworks",
    "cybersecurity threats and vulnerabilities",
    "cloud computing advancements (AWS/GCP/Azure)",
    "open source project releases and updates",
]


class NightShift:
    """
    Autonomous Researcher (Night Shift).
    Runs scheduled deep-dives into tech news and documentation,
    compiling concise daily briefings for Sir.
    """

    def __init__(self) -> None:
        self._briefing_cache: Dict[str, Any] = {}
        self._last_briefing: Optional[str] = None

    async def register_schedules(self) -> None:
        scheduler.schedule_cron(
            "night_shift_daily",
            self.generate_daily_briefing,
            "0 6 * * *",
            description="Generate daily tech briefing",
        )
        scheduler.schedule_interval(
            "night_shift_hourly",
            self._hourly_scan,
            hours=1,
            description="Hourly tech news scan",
        )
        log.info("night_shift_schedules_registered")

    async def _hourly_scan(self) -> None:
        log.info("night_shift_hourly_scan")
        for topic in TOPICS:
            try:
                results = await web_search_service.search(topic, max_results=3)
                if results:
                    log.info("night_shift_findings", topic=topic[:40], results=len(results))
            except Exception as e:
                log.error("night_shift_scan_error", topic=topic[:40], error=str(e))
            await asyncio.sleep(5)

    async def generate_daily_briefing(self) -> str:
        log.info("night_shift_generating_briefing")
        all_findings = []
        for topic in TOPICS:
            try:
                results = await web_search_service.search_and_summarize(topic)
                if results:
                    all_findings.append(f"=== {topic} ===\n{results}")
            except Exception as e:
                log.error("briefing_search_error", topic=topic[:40], error=str(e))
            await asyncio.sleep(3)

        combined = "\n\n".join(all_findings) if all_findings else "No significant findings today."

        brief = await llm_service.get_response(
            user_message=(
                "Compile a concise daily briefing from the search results below. "
                "Format: Executive Summary (3 bullets), Key Developments (5 items), "
                "Action Items (what Sir should know). Be professional and direct."
                f"\n\nSearch Results:\n{combined}"
            ),
            inject_memory=False,
            system_instructions=(
                "You are JARVIS. Generate a crisp, professional daily tech briefing "
                "for Sir. No fluff, no roleplay. Just the facts."
            ),
        )

        self._last_briefing = brief
        self._briefing_cache[datetime.utcnow().isoformat()] = brief

        log.info("night_shift_briefing_generated", length=len(brief))
        return brief

    def get_last_briefing(self) -> Optional[str]:
        return self._last_briefing


night_shift = NightShift()
