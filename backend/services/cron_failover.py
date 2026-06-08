# ====================================================================
# JARVIS OMEGA — Automated Cron/Failover Watchdog
# ====================================================================
"""
Background watchdog process running every 60 seconds to monitor core subsystems,
auto-restart stalled services, and escalate critical alerts to the Sound Engine.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from backend.scheduler import scheduler
from backend.memory.sqlite_memory import sqlite_memory
from backend.websocket_manager import ws_manager
from backend.services.sound_engine import sound_engine, JarvisEvent
from backend.health_monitor import health_monitor
from shared.constants import HealthState
from shared.logger import get_logger

log = get_logger("cron_failover")


class CronFailoverWatchdog:
    """
    Monitors WebSocket connection hub, scheduler, and memory engine.
    Restarts them if stalled and triggers auditory alerts on failure.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = 60.0  # Run every 60 seconds

    async def start(self) -> None:
        """Start the watchdog task."""
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        log.info("cron_failover_watchdog_started")

    async def stop(self) -> None:
        """Stop the watchdog task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("cron_failover_watchdog_stopped")

    async def _watchdog_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                await self.run_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("cron_failover_watchdog_loop_error", error=str(e))

    async def run_checks(self) -> None:
        """Runs health checks on key subsystems."""
        log.debug("watchdog_running_subsystem_checks")

        # 1. Check Scheduler
        try:
            sched_health = scheduler.get_health()
            if not sched_health["running"]:
                log.warning("watchdog_scheduler_not_running_attempting_restart")
                health_monitor.update_component_health(
                    "Scheduler",
                    HealthState.WARNING,
                    "Scheduler stopped, restarting..."
                )
                await scheduler.start()
                await sound_engine.jarvis_alert(JarvisEvent.SERVER_RESTART)
            else:
                health_monitor.update_component_health(
                    "Scheduler",
                    HealthState.HEALTHY,
                    "Scheduler active and persistent"
                )
        except Exception as e:
            log.error("watchdog_scheduler_check_failed", error=str(e))
            health_monitor.update_component_health(
                "Scheduler",
                HealthState.CRITICAL,
                f"Scheduler query failed: {str(e)}"
            )
            await sound_engine.jarvis_alert(JarvisEvent.HEARTBEAT_LOST)

        # 2. Check Memory Engine (SQLite)
        try:
            # Query stats to test DB connection and TF-IDF memory table accessibility
            stats = await sqlite_memory.get_stats()
            log.debug("watchdog_memory_engine_status", total_memories=stats.get("total", 0))
            health_monitor.update_component_health(
                "MemoryEngine",
                HealthState.HEALTHY,
                f"SQLite memories nominal. Count: {stats.get('total', 0)}"
            )
        except Exception as e:
            log.error("watchdog_memory_check_failed_attempting_reinit", error=str(e))
            health_monitor.update_component_health(
                "MemoryEngine",
                HealthState.CRITICAL,
                f"SQLite query failed: {str(e)}. Re-initializing..."
            )
            await sound_engine.jarvis_alert(JarvisEvent.DB_CONNECTION_LOST)
            try:
                await sqlite_memory.initialize()
                log.info("watchdog_memory_engine_reinitialized")
                await sound_engine.jarvis_alert(JarvisEvent.DB_RECONNECTED)
            except Exception as reinit_err:
                log.critical("watchdog_memory_engine_reinit_failed", error=str(reinit_err))

        # 3. Check WebSocket Connections Status
        try:
            conn_count = ws_manager.connection_count
            log.debug("watchdog_websocket_status", connection_count=conn_count)
            health_monitor.update_component_health(
                "WebSocketManager",
                HealthState.HEALTHY,
                f"Active connections: {conn_count}"
            )
        except Exception as e:
            log.error("watchdog_websocket_check_failed", error=str(e))
            health_monitor.update_component_health(
                "WebSocketManager",
                HealthState.WARNING,
                f"WebSocket metrics query failed: {str(e)}"
            )

        # 4. Check Autonomous Scraper
        try:
            from backend.services.autonomous_scraper import autonomous_scraper
            if not autonomous_scraper._running:
                log.warning("watchdog_scraper_not_running_attempting_restart")
                autonomous_scraper.start()
                log.info("watchdog_scraper_restarted")
        except Exception as e:
            log.error("watchdog_scraper_check_failed", error=str(e))


cron_failover = CronFailoverWatchdog()
