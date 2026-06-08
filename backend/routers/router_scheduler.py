"""
Scheduled Tasks Router — schedule one-time, interval, and cron tasks
via the existing APScheduler. Also provides a goal-execution endpoint.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.scheduler import scheduler
from backend.services.goal_executor import goal_executor
from backend.task_manager import task_manager
from backend.websocket_manager import ws_manager
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger
from shared.models import TaskDefinition

log = get_logger("router_scheduler")
router = APIRouter(prefix="/api/scheduler", tags=["Scheduler"])


class ScheduleRequest(BaseModel):
    title: str
    description: str = ""
    schedule_type: str  # "once", "interval", "cron"
    run_at: Optional[str] = None  # ISO datetime for "once"
    interval_seconds: Optional[int] = None
    interval_minutes: Optional[int] = None
    interval_hours: Optional[int] = None
    cron_expression: Optional[str] = None
    agent_type: str = "os"
    payload: Dict[str, Any] = {}


class GoalRequest(BaseModel):
    goal: str
    max_iterations: int = 1000
    timeout_seconds: int = 7200
    context: Optional[Dict[str, Any]] = None


@router.post("/schedule")
async def schedule_task(req: ScheduleRequest) -> Dict[str, Any]:
    """Schedule a one-time, interval, or cron task."""
    job_id = f"scheduled_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    task_kwargs = {
        "title": req.title,
        "description": req.description,
        "agent_type": req.agent_type,
        "payload": req.payload
    }

    try:
        if req.schedule_type == "once":
            if not req.run_at:
                raise HTTPException(status_code=400, detail="run_at is required for 'once' schedule")
            run_dt = datetime.fromisoformat(req.run_at)
            scheduler.schedule_once(
                job_id=job_id,
                func="execute_scheduled_task",
                run_at=run_dt,
                kwargs=task_kwargs,
                description=req.description or req.title,
            )
        elif req.schedule_type == "interval":
            scheduler.schedule_interval(
                job_id=job_id,
                func="execute_scheduled_task",
                kwargs=task_kwargs,
                seconds=req.interval_seconds or 0,
                minutes=req.interval_minutes or 0,
                hours=req.interval_hours or 0,
                description=req.description or req.title,
            )
        elif req.schedule_type == "cron":
            if not req.cron_expression:
                raise HTTPException(status_code=400, detail="cron_expression is required for 'cron' schedule")
            scheduler.schedule_cron(
                job_id=job_id,
                func="execute_scheduled_task",
                cron_expression=req.cron_expression,
                kwargs=task_kwargs,
                description=req.description or req.title,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown schedule_type: {req.schedule_type}")

        return {
            "job_id": job_id,
            "schedule_type": req.schedule_type,
            "title": req.title,
            "status": "scheduled",
        }
    except Exception as e:
        log.error("schedule_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_scheduled_jobs() -> Dict[str, Any]:
    """List all scheduled jobs."""
    jobs = scheduler.get_jobs()
    return {"jobs": jobs, "count": len(jobs)}


@router.delete("/jobs/{job_id}")
async def cancel_scheduled_job(job_id: str) -> Dict[str, Any]:
    """Cancel a scheduled job."""
    success = scheduler.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"status": "cancelled", "job_id": job_id}


@router.post("/execute-goal")
async def execute_goal(req: GoalRequest) -> Dict[str, Any]:
    """
    Execute a complex, multi-phase goal.
    The Mega Goal Engine decomposes the goal into phases and steps,
    executes them with checkpointing, and supports up to 1000+ iterations.
    Runs as a background task to avoid HTTP timeout.
    """
    if not req.goal or not req.goal.strip():
        raise HTTPException(status_code=400, detail="Goal is required")

    log.info("mega_goal_requested", goal=req.goal[:120], max_iter=req.max_iterations)

    # Launch in background so the HTTP response returns immediately
    async def _run_goal():
        return await goal_executor.execute_goal(
            goal=req.goal.strip(),
            max_iterations=req.max_iterations,
            timeout_seconds=req.timeout_seconds,
            context=req.context,
        )

    task = asyncio.create_task(_run_goal())

    # Wait briefly to capture the goal_id
    await asyncio.sleep(0.3)

    running = goal_executor.get_running_goals()
    goal_ids = list(running.keys())
    latest_id = goal_ids[-1] if goal_ids else "unknown"

    return {
        "status": "started",
        "goal_id": latest_id,
        "goal": req.goal.strip()[:120],
        "max_iterations": req.max_iterations,
        "timeout_seconds": req.timeout_seconds,
        "message": "Goal execution started in background. Poll /api/scheduler/goals/{goal_id} for progress.",
    }


@router.get("/goals/running")
async def get_running_goals() -> Dict[str, Any]:
    """Get all currently running goal executions."""
    goals = goal_executor.get_running_goals()
    return {"running_goals": goals, "count": len(goals)}


@router.get("/goals/checkpointed")
async def list_checkpointed_goals() -> Dict[str, Any]:
    """List all goals with saved checkpoints on disk."""
    goals = goal_executor.list_checkpointed_goals()
    return {"goals": goals, "count": len(goals)}


@router.get("/goals/{goal_id}")
async def get_goal_progress(goal_id: str) -> Dict[str, Any]:
    """Get detailed progress of a specific goal (running or checkpointed)."""
    progress = goal_executor.get_goal_progress(goal_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return progress


@router.post("/goals/{goal_id}/cancel")
async def cancel_goal(goal_id: str) -> Dict[str, Any]:
    """Cancel a running goal. The goal state is checkpointed so it can be resumed later."""
    result = goal_executor.cancel_goal(goal_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} is not currently running")
    return result


@router.post("/goals/{goal_id}/resume")
async def resume_goal(goal_id: str) -> Dict[str, Any]:
    """Resume a checkpointed goal from where it left off."""
    log.info("goal_resume_requested", goal_id=goal_id)

    async def _resume():
        return await goal_executor.resume_goal(goal_id)

    task = asyncio.create_task(_resume())
    await asyncio.sleep(0.3)

    return {
        "status": "resuming",
        "goal_id": goal_id,
        "message": "Goal resuming from checkpoint. Poll /api/scheduler/goals/{goal_id} for progress.",
    }

