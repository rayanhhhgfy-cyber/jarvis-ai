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

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.logger import get_logger

log = get_logger("scheduler")


class TaskScheduler:
    """
    Manages scheduled tasks: one-time, recurring, interval-based,
    and cron-expression tasks.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: Dict[str, Dict[str, Any]] = {}

    async def start(self) -> None:
        """Start the scheduler."""
        self._scheduler.start()
        log.info("scheduler_started")

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._scheduler.shutdown(wait=True)
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
            job = self._scheduler.get_job(job_id)
            result.append({
                "job_id": job_id,
                **info,
                "next_run": str(job.next_run_time) if job else "N/A",
                "active": job is not None,
            })
        return result

    @property
    def job_count(self) -> int:
        return len(self._scheduler.get_jobs())


# Global scheduler instance
scheduler = TaskScheduler()
