from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.task_manager import task_manager
from shared.constants import TaskPriority, TaskStatus
from shared.logger import get_logger
from shared.models import TaskDefinition

log = get_logger("tasks_router")
router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


PRIORITY_ORDER = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}


@router.post("")
async def create_task(task: TaskDefinition):
    task_id = await task_manager.create_task(task)
    return {"task_id": task_id, "status": "queued"}


@router.get("")
async def list_tasks(limit: int = 50, status: Optional[str] = None, priority: Optional[str] = None):
    tasks = task_manager.get_all_tasks(limit=limit)
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    if priority:
        tasks = [t for t in tasks if t.priority.value == priority]
    tasks.sort(key=lambda t: (PRIORITY_ORDER.get(t.priority, 99), t.created_at or datetime.min))
    return [t.model_dump() for t in tasks]


@router.get("/next")
async def get_next_task():
    tasks = task_manager.get_all_tasks(limit=100)
    pending = [t for t in tasks if t.status in (TaskStatus.QUEUED, TaskStatus.AWAITING_APPROVAL)]
    if not pending:
        return {"task": None}
    pending.sort(key=lambda t: (PRIORITY_ORDER.get(t.priority, 99), t.created_at or datetime.min))
    return {"task": pending[0].model_dump(), "remaining": len(pending) - 1}


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = task_manager.get_result(task_id)
    return {
        "task": task.model_dump(),
        "result": result.model_dump() if result else None,
    }


@router.patch("/{task_id}")
async def update_task(task_id: str, body: Dict[str, Any]):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if "title" in body:
        task.title = body["title"]
    if "description" in body:
        task.description = body["description"]
    if "priority" in body:
        try:
            task.priority = TaskPriority(body["priority"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {body['priority']}")
    if "status" in body:
        try:
            new_status = TaskStatus(body["status"])
            if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = datetime.utcnow()
            elif new_status == TaskStatus.RUNNING:
                task.started_at = datetime.utcnow()
            task.status = new_status
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body['status']}")

    log.info("task_updated", task_id=task_id, updates=body)
    return task.model_dump()


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = TaskStatus.CANCELLED
    task.completed_at = datetime.utcnow()
    return {"status": "deleted", "task_id": task_id}


@router.get("/stats/priorities")
async def task_priority_stats():
    tasks = task_manager.get_all_tasks(limit=500)
    counts: Dict[str, int] = {}
    for p in TaskPriority:
        counts[p.value] = 0
    for t in tasks:
        if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED):
            counts[t.priority.value] = counts.get(t.priority.value, 0) + 1
    return {"priorities": counts, "total_active": sum(counts.values())}
