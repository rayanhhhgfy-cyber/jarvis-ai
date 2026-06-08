from __future__ import annotations

import asyncio
import json
import psutil
from datetime import datetime
from typing import List, Optional
from shared.logger import get_logger
from shared.constants import AgentType, MemoryCategory
from backend.services.agent_tracker import agent_tracker
from backend.services.web_search_service import web_search_service
from shared.models import MemoryEntry

log = get_logger("autonomous_scraper")

DEFAULT_INTERVAL = 1800   # 30 minutes (doubled from 15)
STARTUP_DELAY   = 120     # Wait 2 minutes after boot before first scrape
CPU_CEILING     = 60.0    # Skip scrape if CPU > 60%
MEM_CEILING     = 85.0    # Skip scrape if memory > 85%


class AutonomousScraper:
    """
    24/7 background worker that scrapes the web for data matching the user's
    custom instructions and suggestions, summarizing and storing it in local SQLite memory.

    Resource-aware: skips rounds when CPU or memory are under pressure.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval = DEFAULT_INTERVAL

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        log.info("autonomous_scraper_started", interval_seconds=self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("autonomous_scraper_stopped")

    def _system_ok(self) -> bool:
        """Return True only when the system has enough headroom to scrape."""
        try:
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory().percent
            if cpu > CPU_CEILING:
                log.info("scraper_skipping_high_cpu", cpu=cpu)
                return False
            if mem > MEM_CEILING:
                log.info("scraper_skipping_high_mem", mem=mem)
                return False
        except Exception:
            pass
        return True

    async def _run_loop(self) -> None:
        # Wait on startup so the app can fully boot without added load
        log.info("autonomous_scraper_startup_delay", seconds=STARTUP_DELAY)
        await asyncio.sleep(STARTUP_DELAY)

        while self._running:
            try:
                if self._system_ok():
                    await self.scrape_round()
                else:
                    log.info("autonomous_scraper_round_skipped_resources")
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("autonomous_scraper_round_failed", error=str(e))

            # Sleep until next round
            await asyncio.sleep(self._interval)

    async def scrape_round(self) -> None:
        """Executes a single round of autonomous scraping and memory injection."""
        log.info("starting_autonomous_scrape_round")

        # 1. Fetch dynamic search queries based on user settings
        queries = await self.get_search_queries()
        log.info("autonomous_queries_derived", count=len(queries), queries=queries)

        for query in queries:
            if not self._running:
                break

            # Re-check resources between queries
            if not self._system_ok():
                log.info("scraper_aborting_round_resources")
                break

            try:
                agent_tracker.mark_running(AgentType.RESEARCH, f"Scraping web: {query}")

                log.info("scraping_query", query=query)
                search_res = await web_search_service.search_web(query, max_results=3)
                results = search_res.get("results", [])
                log.info("web_search_completed", query=query, results=len(results))

                if not results:
                    continue

                for res in results[:2]:
                    title   = res.get("title", "")
                    snippet = res.get("snippet", "")
                    url     = res.get("url", "")

                    if not snippet:
                        continue

                    # Store the raw snippet directly — no LLM summarization
                    # (LLM calls during background scraping caused CPU spikes)
                    content = f"[Scrape: {query}] {title} — {snippet[:500]} (Source: {url})"
                    memory_entry = MemoryEntry(
                        category=MemoryCategory.KNOWLEDGE,
                        content=content,
                        source="autonomous_scraper",
                        tags=["scraped", query.lower().replace(" ", "_")],
                        metadata={"url": url, "scraped_at": datetime.utcnow().isoformat()}
                    )
                    from backend.memory.sqlite_memory import sqlite_memory
                    mem_id = await sqlite_memory.store(memory_entry)
                    log.info("autonomous_memory_added", id=mem_id, query=query)

            except Exception as query_err:
                log.error("autonomous_query_scrape_failed", query=query, error=str(query_err))
            finally:
                agent_tracker.mark_idle(AgentType.RESEARCH)

            # Polite pause between queries to avoid rate limits
            await asyncio.sleep(8)

        log.info("finished_autonomous_scrape_round")

    async def get_search_queries(self) -> List[str]:
        """Derives search queries based on custom instructions and custom suggestions."""
        from backend.services.settings_service import load

        user_settings = load(user_id="default")
        suggestions = user_settings.get("custom_suggestions", "").strip()
        ctx_a = user_settings.get("custom_instructions_a", "").strip()

        default_queries = [
            "latest artificial intelligence agent breakthroughs",
            "cutting edge tech news this week",
            "modern marketing agency digital automation tools",
        ]

        if not suggestions and not ctx_a:
            return default_queries

        # Build queries from settings text without calling the LLM
        # (saves resources; LLM can still be called on-demand via chat)
        context = f"{ctx_a} {suggestions}".lower()
        keyword_queries: List[str] = []
        if "wedding" in context:
            keyword_queries.append("wedding planning tips 2025")
        if "marketing" in context or "agency" in context:
            keyword_queries.append("digital marketing agency automation tools")
        if "ai" in context or "artificial intelligence" in context:
            keyword_queries.append("AI agent tools breakthroughs 2025")
        if "social media" in context or "instagram" in context:
            keyword_queries.append("Instagram growth strategy for agencies 2025")

        return (keyword_queries + default_queries)[:3]


autonomous_scraper = AutonomousScraper()
