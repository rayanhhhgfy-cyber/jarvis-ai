# ====================================================================
# JARVIS OMEGA — Hardened Task Scheduler
# ====================================================================
"""
APScheduler-based task scheduler with SQLite persistence for jobs,
startup recovery of missed one-time jobs, and automatic exponential backoff retries.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.logger import get_logger

log = get_logger("scheduler")

# ====================================================================
# SERIALIZABLE FUNCTION REGISTRY
# ====================================================================
# Resolves string names of functions to their actual async/sync callables.

async def run_weekly_improvement():
    try:
        from backend.improvement.self_improvement import self_improvement
        await self_improvement._weekly_analysis()
    except Exception as e:
        log.error("run_weekly_improvement_error", error=str(e))
        raise

async def run_daily_briefing():
    try:
        from backend.research.night_shift import night_shift
        await night_shift.generate_daily_briefing()
    except Exception as e:
        log.error("run_daily_briefing_error", error=str(e))
        raise

async def run_hourly_scan():
    try:
        from backend.research.night_shift import night_shift
        await night_shift._hourly_scan()
    except Exception as e:
        log.error("run_hourly_scan_error", error=str(e))
        raise

async def run_workflow_by_id(workflow_id: str):
    try:
        from backend.routers.router_patterns import pattern_detector, _dispatch_and_wait
        from backend.websocket_manager import ws_manager
        
        workflows = pattern_detector.get_workflows()
        workflow = None
        for wf in workflows:
            if wf["workflow_id"] == workflow_id:
                workflow = wf
                break
        if not workflow:
            log.warning("run_workflow_by_id_missing_workflow", workflow_id=workflow_id)
            return

        results = []
        for i, cmd in enumerate(workflow.get("commands", [])):
            try:
                # Execute step
                result = await _dispatch_and_wait(cmd, f"Workflow step {i + 1}: {cmd[:60]}", timeout=30.0)
                results.append({"step": i + 1, "command": cmd, "success": result.get("completed", False)})
            except Exception as e:
                results.append({"step": i + 1, "command": cmd, "success": False, "error": str(e)})

        try:
            await ws_manager.broadcast({
                "type": "workflow_executed",
                "payload": {
                    "workflow_id": workflow_id,
                    "name": workflow.get("name", ""),
                    "results": results,
                    "timestamp": datetime.utcnow().isoformat()
                },
            })
        except Exception:
            pass
    except Exception as e:
        log.error("run_workflow_by_id_error", workflow_id=workflow_id, error=str(e))
        raise

async def execute_scheduled_task(title: str, description: str, agent_type: str, payload: dict):
    try:
        from backend.task_manager import task_manager
        from backend.websocket_manager import ws_manager
        from shared.constants import AgentType
        from shared.models import TaskDefinition

        try:
            agent_enum = AgentType(agent_type)
        except ValueError:
            agent_enum = AgentType.OS

        task = TaskDefinition(
            title=title,
            description=description,
            agent_type=agent_enum,
            payload=payload,
        )
        task_id = await task_manager.create_task(task)
        log.info("scheduled_task_executed", task_id=task_id)

        try:
            await ws_manager.broadcast({
                "type": "scheduled_task_executed",
                "payload": {
                    "task_id": task_id,
                    "title": title,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            })
        except Exception:
            pass
    except Exception as e:
        log.error("execute_scheduled_task_error", error=str(e))
        raise


FUNCTION_MAP: Dict[str, Callable] = {
    "weekly_analysis": run_weekly_improvement,
    "run_weekly_improvement": run_weekly_improvement,
    "generate_daily_briefing": run_daily_briefing,
    "run_daily_briefing": run_daily_briefing,
    "_hourly_scan": run_hourly_scan,
    "run_hourly_scan": run_hourly_scan,
    "run_workflow_by_id": run_workflow_by_id,
    "execute_scheduled_task": execute_scheduled_task,
}


class TaskScheduler:
    """
    Harden TaskScheduler using SQLite persistence, recovery on restart,
    and automatic retries with exponential backoff.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._conn: Optional[sqlite3.Connection] = None
        self._missed_jobs_count = 0
        self._failed_jobs_count = 0

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            from backend.config import settings
            db_path = Path(settings.sqlite_db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            cursor = self._conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    func_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    kwargs_json TEXT NOT NULL,
                    trigger_config_json TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()
        return self._conn

    async def start(self) -> None:
        """Start the scheduler and recover missed tasks."""
        self._get_conn()
        self._scheduler.start()
        log.info("scheduler_started")
        await self._recover_and_reschedule()

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._scheduler.shutdown(wait=True)
        if self._conn:
            self._conn.close()
            self._conn = None
        log.info("scheduler_stopped")

    async def retry_wrapper(self, job_id: str, func_name: str, args: list, kwargs: dict) -> None:
        """Runs the scheduled job with automatic retries and exponential backoff."""
        func = FUNCTION_MAP.get(func_name)
        if not func:
            log.error("retry_wrapper_missing_func", func_name=func_name)
            self._failed_jobs_count += 1
            return

        retries = 3
        delay = 1.0
        for attempt in range(1, retries + 1):
            try:
                log.info("running_scheduled_job", job_id=job_id, attempt=attempt)
                if asyncio.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    func(*args, **kwargs)
                log.info("scheduled_job_success", job_id=job_id)
                
                # If it's a one-time job, remove from SQLite persistence
                job_info = self._jobs.get(job_id)
                if job_info and job_info["type"] == "once":
                    self.cancel_job(job_id)
                return
            except Exception as e:
                log.error("scheduled_job_failed", job_id=job_id, attempt=attempt, error=str(e))
                if attempt == retries:
                    self._failed_jobs_count += 1
                    log.critical("scheduled_job_max_retries_exhausted", job_id=job_id)
                    break
                await asyncio.sleep(delay)
                delay *= 2.0

    async def _recover_and_reschedule(self) -> None:
        """Reschedules saved jobs and executes missed one-time jobs immediately."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduler_jobs")
        rows = cursor.fetchall()

        now = datetime.utcnow()
        for row in rows:
            job_id = row["id"]
            job_type = row["type"]
            func_name = row["func_name"]
            args = json.loads(row["args_json"])
            kwargs = json.loads(row["kwargs_json"])
            trigger_config = json.loads(row["trigger_config_json"])
            desc = row["description"] or ""

            if func_name not in FUNCTION_MAP:
                log.error("recovery_failed_missing_function", job_id=job_id, func_name=func_name)
                continue

            try:
                if job_type == "once":
                    run_at = datetime.fromisoformat(trigger_config["run_at"])
                    if run_at < now:
                        # Missed task recovery
                        log.warning("running_missed_once_job_immediately", job_id=job_id, run_at=run_at.isoformat())
                        self._missed_jobs_count += 1
                        asyncio.create_task(self.retry_wrapper(job_id, func_name, args, kwargs))
                    else:
                        self._scheduler.add_job(
                            self.retry_wrapper,
                            trigger=DateTrigger(run_date=run_at),
                            id=job_id,
                            args=[job_id, func_name, args, kwargs],
                            replace_existing=True
                        )
                elif job_type == "interval":
                    self._scheduler.add_job(
                        self.retry_wrapper,
                        trigger=IntervalTrigger(
                            seconds=trigger_config.get("seconds", 0),
                            minutes=trigger_config.get("minutes", 0),
                            hours=trigger_config.get("hours", 0)
                        ),
                        id=job_id,
                        args=[job_id, func_name, args, kwargs],
                        replace_existing=True
                    )
                elif job_type == "cron":
                    cron_expr = trigger_config["cron"]
                    parts = cron_expr.split()
                    trigger = CronTrigger(
                        minute=parts[0] if len(parts) > 0 else "*",
                        hour=parts[1] if len(parts) > 1 else "*",
                        day=parts[2] if len(parts) > 2 else "*",
                        month=parts[3] if len(parts) > 3 else "*",
                        day_of_week=parts[4] if len(parts) > 4 else "*",
                    )
                    self._scheduler.add_job(
                        self.retry_wrapper,
                        trigger=trigger,
                        id=job_id,
                        args=[job_id, func_name, args, kwargs],
                        replace_existing=True
                    )

                self._jobs[job_id] = {
                    "type": job_type,
                    "description": desc,
                    "func_name": func_name,
                    "created_at": row["created_at"]
                }
            except Exception as e:
                log.error("reschedule_failed_during_recovery", job_id=job_id, error=str(e))

    def _persist_job(
        self,
        job_id: str,
        job_type: str,
        func_name: str,
        args: list,
        kwargs: dict,
        trigger_config: dict,
        description: str
    ) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO scheduler_jobs (
                id, type, func_name, args_json, kwargs_json, trigger_config_json, description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                func_name,
                json.dumps(args),
                json.dumps(kwargs),
                json.dumps(trigger_config),
                description,
                datetime.utcnow().isoformat()
            )
        )
        conn.commit()

    def _unpersist_job(self, job_id: str) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduler_jobs WHERE id = ?", (job_id,))
        conn.commit()

    def schedule_once(
        self,
        job_id: str,
        func: Callable | str,
        run_at: datetime,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        description: str = "",
    ) -> str:
        """Schedule a one-time task."""
        func_name = func if isinstance(func, str) else func.__name__
        resolved_args = args or []
        resolved_kwargs = kwargs or {}

        # Persist
        trigger_config = {"run_at": run_at.isoformat()}
        self._persist_job(job_id, "once", func_name, resolved_args, resolved_kwargs, trigger_config, description)

        # Schedule
        self._scheduler.add_job(
            self.retry_wrapper,
            trigger=DateTrigger(run_date=run_at),
            id=job_id,
            args=[job_id, func_name, resolved_args, resolved_kwargs],
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "type": "once",
            "description": description,
            "func_name": func_name,
            "created_at": datetime.utcnow().isoformat(),
        }
        log.info("job_scheduled_once", job_id=job_id, run_at=run_at.isoformat())
        return job_id

    def schedule_interval(
        self,
        job_id: str,
        func: Callable | str,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        description: str = "",
    ) -> str:
        """Schedule a recurring interval task."""
        func_name = func if isinstance(func, str) else func.__name__
        resolved_args = args or []
        resolved_kwargs = kwargs or {}

        # Persist
        trigger_config = {"seconds": seconds, "minutes": minutes, "hours": hours}
        self._persist_job(job_id, "interval", func_name, resolved_args, resolved_kwargs, trigger_config, description)

        # Schedule
        self._scheduler.add_job(
            self.retry_wrapper,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours),
            id=job_id,
            args=[job_id, func_name, resolved_args, resolved_kwargs],
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "type": "interval",
            "description": description,
            "func_name": func_name,
            "created_at": datetime.utcnow().isoformat(),
        }
        log.info("job_scheduled_interval", job_id=job_id)
        return job_id

    def schedule_cron(
        self,
        job_id: str,
        func: Callable | str,
        cron_expression: str,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        description: str = "",
    ) -> str:
        """Schedule a cron-based task."""
        func_name = func if isinstance(func, str) else func.__name__
        resolved_args = args or []
        resolved_kwargs = kwargs or {}

        # Persist
        trigger_config = {"cron": cron_expression}
        self._persist_job(job_id, "cron", func_name, resolved_args, resolved_kwargs, trigger_config, description)

        # Schedule
        parts = cron_expression.split()
        trigger = CronTrigger(
            minute=parts[0] if len(parts) > 0 else "*",
            hour=parts[1] if len(parts) > 1 else "*",
            day=parts[2] if len(parts) > 2 else "*",
            month=parts[3] if len(parts) > 3 else "*",
            day_of_week=parts[4] if len(parts) > 4 else "*",
        )
        self._scheduler.add_job(
            self.retry_wrapper,
            trigger=trigger,
            id=job_id,
            args=[job_id, func_name, resolved_args, resolved_kwargs],
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "type": "cron",
            "description": description,
            "func_name": func_name,
            "created_at": datetime.utcnow().isoformat(),
        }
        log.info("job_scheduled_cron", job_id=job_id, cron=cron_expression)
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a scheduled job."""
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            self._unpersist_job(job_id)
            log.info("job_cancelled", job_id=job_id)
            return True
        except Exception as e:
            # Check if it exists in DB still
            self._unpersist_job(job_id)
            self._jobs.pop(job_id, None)
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
                "next_run": str(job.next_run_time) if job and job.next_run_time else "N/A",
                "active": job is not None,
            })
        return result

    def get_health(self) -> Dict[str, Any]:
        """Returns scheduler state, job counts, failed count and missed count."""
        return {
            "running": self._scheduler.running,
            "job_count": self.job_count,
            "missed_jobs_count": self._missed_jobs_count,
            "failed_jobs_count": self._failed_jobs_count,
        }

    @property
    def job_count(self) -> int:
        return len(self._scheduler.get_jobs())


# Global scheduler instance
scheduler = TaskScheduler()
