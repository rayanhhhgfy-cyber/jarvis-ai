# ====================================================================
# JARVIS OMEGA — Scheduler
# ====================================================================
"""
APScheduler-based task scheduler: one-time, recurring, conditional,
and event-triggered task scheduling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.logger import get_logger

log = get_logger("scheduler")


def _scheduler_timezone() -> ZoneInfo:
    """All cron jobs fire in Sir's timezone (Asia/Amman).

    The server runs in UTC, so a bare AsyncIOScheduler would fire the
    20:00 digest at 23:00 his time and the 09:00 birthday check at
    noon. Pinning the timezone makes every job fire when its
    description says it does.
    """
    return ZoneInfo("Asia/Amman")


class TaskScheduler:
    """
    Manages scheduled tasks: one-time, recurring, interval-based,
    and cron-expression tasks.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone=_scheduler_timezone())
        self._jobs: Dict[str, Dict[str, Any]] = {}

    async def start(self) -> None:
        """Start the scheduler. Idempotent and restart-safe.

        AsyncIOScheduler captures the running event loop on its FIRST
        start only and never re-captures it. After a shutdown the stored
        loop may be closed (e.g. a TestClient portal closed it), so a
        second start() would schedule work on a dead loop and raise
        ``RuntimeError: Event loop is closed``. Clear the stored loop
        when it is not the current one so start() re-captures it.
        """
        if self._scheduler.running:
            return
        loop = asyncio.get_running_loop()
        stored = self._scheduler._eventloop
        if stored is not None and stored is not loop:
            self._scheduler._eventloop = None
        self._scheduler.start()
        log.info("scheduler_started")

    async def stop(self) -> None:
        """Stop the scheduler gracefully.

        AsyncIOScheduler.shutdown() is dispatched via call_soon_threadsafe
        and returns at once — the real shutdown happens on the loop
        afterwards. Wait until the scheduler actually reports stopped
        (bounded, so shutdown can never hang).
        """
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=True)
        for _ in range(100):
            if self._scheduler.state == STATE_STOPPED:
                break
            await asyncio.sleep(0.02)
        else:
            log.warning("scheduler_stop_timed_out")
        log.info("scheduler_stopped")

    def schedule_once(
        self,
        job_id: str,
        func: Callable,
        run_at: datetime,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        description: str = "",
    ) -> str:
        """Schedule a one-time task."""
        job = self._scheduler.add_job(
            func,
            trigger=DateTrigger(run_date=run_at),
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "type": "once",
            "description": description,
            "run_at": run_at.isoformat(),
            "created_at": datetime.utcnow().isoformat(),
        }
        log.info("job_scheduled_once", job_id=job_id, run_at=run_at.isoformat())
        return job_id

    def schedule_interval(
        self,
        job_id: str,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        description: str = "",
    ) -> str:
        """Schedule a recurring interval task."""
        job = self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours),
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "type": "interval",
            "description": description,
            "interval": f"{hours}h {minutes}m {seconds}s",
            "created_at": datetime.utcnow().isoformat(),
        }
        log.info("job_scheduled_interval", job_id=job_id)
        return job_id

    def schedule_cron(
        self,
        job_id: str,
        func: Callable,
        cron_expression: str,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        description: str = "",
    ) -> str:
        """Schedule a cron-based task."""
        parts = cron_expression.split()
        trigger = CronTrigger(
            minute=parts[0] if len(parts) > 0 else "*",
            hour=parts[1] if len(parts) > 1 else "*",
            day=parts[2] if len(parts) > 2 else "*",
            month=parts[3] if len(parts) > 3 else "*",
            day_of_week=parts[4] if len(parts) > 4 else "*",
        )
        job = self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "type": "cron",
            "description": description,
            "cron": cron_expression,
            "created_at": datetime.utcnow().isoformat(),
        }
        log.info("job_scheduled_cron", job_id=job_id, cron=cron_expression)
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a scheduled job."""
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            log.info("job_cancelled", job_id=job_id)
            return True
        except Exception as e:
            log.error("job_cancel_error", job_id=job_id, error=str(e))
            return False

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all scheduled jobs."""
        result = []
        for job_id, info in self._jobs.items():
            job = None
            next_run = "N/A"
            active = False
            try:
                job = self._scheduler.get_job(job_id)
                if job is not None:
                    active = True
                    # APScheduler sets ``next_run_time`` only when the
                    # scheduler is actually running; be defensive about it.
                    next_run = str(getattr(job, "next_run_time", None) or "N/A")
            except Exception as e:
                log.debug("get_job_failed", job_id=job_id, error=str(e))
            result.append({
                "job_id": job_id,
                **info,
                "next_run": next_run,
                "active": active,
            })
        return result

    @property
    def job_count(self) -> int:
        return len(self._scheduler.get_jobs())


# Global scheduler instance
scheduler = TaskScheduler()
