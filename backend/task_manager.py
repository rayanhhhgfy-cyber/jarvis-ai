# ====================================================================
# JARVIS OMEGA — Task Manager
# ====================================================================
"""
Task lifecycle management: creation, queuing, assignment,
progress tracking, completion, failure handling, and retry logic.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from shared.constants import AgentType, EventType, TaskPriority, TaskStatus
from shared.logger import get_logger
from shared.models import TaskDefinition, TaskResult

log = get_logger("task_manager")


class TaskManager:
    """
    Manages the full lifecycle of tasks across the system.
    Tasks flow: QUEUED → ASSIGNED → RUNNING → COMPLETED/FAILED
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskDefinition] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._results: Dict[str, TaskResult] = {}
        self._event_bus = None
        self._lock = asyncio.Lock()

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    async def create_task(self, task: TaskDefinition) -> str:
        """Create and queue a new task."""
        async with self._lock:
            self._tasks[task.task_id] = task

        # Priority queue uses (priority_value, timestamp, task_id)
        priority_map = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.MEDIUM: 2,
            TaskPriority.LOW: 3,
        }
        priority_val = priority_map.get(task.priority, 2)
        await self._queue.put((priority_val, datetime.utcnow().timestamp(), task.task_id))

        log.info(
            "task_created",
            task_id=task.task_id,
            title=task.title,
            agent_type=task.agent_type.value,
            priority=task.priority.value,
        )

        if self._event_bus:
            await self._event_bus.publish(
                EventType.TASK_CREATED,
                {"task_id": task.task_id, "title": task.title, "priority": task.priority.value},
            )

        return task.task_id

    async def get_next_task(self) -> Optional[TaskDefinition]:
        """Get the next highest-priority task from the queue."""
        try:
            priority_val, ts, task_id = self._queue.get_nowait()
            return self._tasks.get(task_id)
        except asyncio.QueueEmpty:
            return None

    async def start_task(self, task_id: str, agent_id: str) -> bool:
        """Mark a task as started by an agent."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.RUNNING
        task.assigned_agent_id = agent_id
        task.started_at = datetime.utcnow()

        log.info("task_started", task_id=task_id, agent_id=agent_id)

        if self._event_bus:
            await self._event_bus.publish(
                EventType.TASK_STARTED,
                {"task_id": task_id, "agent_id": agent_id},
            )

        return True

    async def complete_task(self, result: TaskResult) -> None:
        """Mark a task as completed with results."""
        task = self._tasks.get(result.task_id)
        if not task:
            return

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.result = result.result

        self._results[result.task_id] = result

        log.info(
            "task_completed",
            task_id=result.task_id,
            agent_id=result.agent_id,
            execution_time=result.execution_time,
        )

        if self._event_bus:
            await self._event_bus.publish(
                EventType.TASK_COMPLETED,
                {
                    "task_id": result.task_id,
                    "agent_id": result.agent_id,
                    "execution_time": result.execution_time,
                },
            )

    async def fail_task(self, task_id: str, error: str, agent_id: str = "") -> bool:
        """Mark a task as failed. Automatically retries if under max_retries."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.retry_count += 1

        if task.retry_count <= task.max_retries:
            task.status = TaskStatus.RETRYING
            log.warning(
                "task_retrying",
                task_id=task_id,
                retry=task.retry_count,
                max_retries=task.max_retries,
                error=error,
            )
            # Re-queue with same priority
            await self.create_task(task)
            return True
        else:
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.utcnow()

            log.error("task_failed", task_id=task_id, error=error, retries_exhausted=True)

            if self._event_bus:
                await self._event_bus.publish(
                    EventType.TASK_FAILED,
                    {"task_id": task_id, "error": error, "agent_id": agent_id},
                )

            return False

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        log.info("task_cancelled", task_id=task_id)
        return True

    def get_task(self, task_id: str) -> Optional[TaskDefinition]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        """Get a task result by ID."""
        return self._results.get(task_id)

    def get_tasks_by_status(self, status: TaskStatus) -> List[TaskDefinition]:
        """Get all tasks with a given status."""
        return [t for t in self._tasks.values() if t.status == status]

    def get_tasks_by_agent(self, agent_type: AgentType) -> List[TaskDefinition]:
        """Get all tasks assigned to a specific agent type."""
        return [t for t in self._tasks.values() if t.agent_type == agent_type]

    def get_all_tasks(self, limit: int = 100) -> List[TaskDefinition]:
        """Get all tasks, most recent first."""
        sorted_tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return sorted_tasks[:limit]

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def total_tasks(self) -> int:
        return len(self._tasks)

    def get_stats(self) -> Dict[str, int]:
        """Get task statistics."""
        stats: Dict[str, int] = defaultdict(int)
        for task in self._tasks.values():
            stats[task.status.value] += 1
        stats["total"] = len(self._tasks)
        stats["queued_in_queue"] = self._queue.qsize()
        return dict(stats)


# Global task manager instance
task_manager = TaskManager()
