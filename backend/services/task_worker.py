"""
Background task worker that picks tasks from the task manager queue
and delegates them to the agent orchestrator for execution.
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime
from typing import Optional

from shared.constants import AgentType, AgentStatus, TaskStatus
from shared.logger import get_logger
from shared.models import TaskResult

log = get_logger("task_worker")


class TaskWorker:
    """
    Background worker that polls the task manager queue and executes
    tasks via the agent orchestrator.

    Runs as a single long-lived asyncio task in the event loop.
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._task_manager = None
        self._orchestrator = None
        self._agent_tracker = None

    def setup(self, task_manager, orchestrator, agent_tracker):
        """Inject dependencies after startup."""
        self._task_manager = task_manager
        self._orchestrator = orchestrator
        self._agent_tracker = agent_tracker

    def start(self):
        """Launch the background worker loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._worker_loop())
        log.info("task_worker_started")

    async def stop(self):
        """Stop the worker loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("task_worker_stopped")

    async def _worker_loop(self):
        """Main loop: poll queue, execute tasks, report results."""
        while self._running:
            try:
                task_def = None
                if self._task_manager:
                    task_def = await self._task_manager.get_next_task()

                if task_def is None:
                    await asyncio.sleep(0.5)
                    continue

                log.info("worker_picked_task", task_id=task_def.task_id, title=task_def.title, agent=str(task_def.agent_type.value))

                # Mark running in task_manager
                agent_id = f"worker-{task_def.agent_type.value}"
                if self._task_manager:
                    await self._task_manager.start_task(task_def.task_id, agent_id)

                # Track in agent_tracker
                if self._agent_tracker:
                    self._agent_tracker.mark_running(task_def.agent_type, task_def.description or task_def.title)

                # Execute via orchestrator
                if self._orchestrator:
                    try:
                        result = await self._orchestrator.execute_task(task_def)
                    except Exception as exec_err:
                        log.error("worker_orchestrator_failed", task_id=task_def.task_id, error=str(exec_err))
                        result = TaskResult(
                            task_id=task_def.task_id,
                            agent_id=agent_id,
                            status=TaskStatus.FAILED,
                            error=f"Orchestrator error: {str(exec_err)}\n{traceback.format_exc()}",
                        )
                else:
                    result = TaskResult(
                        task_id=task_def.task_id,
                        agent_id=agent_id,
                        status=TaskStatus.FAILED,
                        error="No orchestrator available",
                    )

                # Report back
                if self._task_manager:
                    if result.status == TaskStatus.COMPLETED:
                        await self._task_manager.complete_task(result)
                    elif result.status == TaskStatus.FAILED:
                        await self._task_manager.fail_task(task_def.task_id, result.error or "Unknown error", agent_id)
                    else:
                        await self._task_manager.complete_task(result)

                # Update agent_tracker
                if self._agent_tracker:
                    if result.status == TaskStatus.COMPLETED:
                        self._agent_tracker.mark_idle(task_def.agent_type)
                    elif result.status == TaskStatus.FAILED:
                        self._agent_tracker.mark_failed(task_def.agent_type, result.error or "Task failed")

                log.info("worker_task_completed", task_id=task_def.task_id, status=result.status.value)

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                log.error("worker_loop_error", error=str(loop_err))
                await asyncio.sleep(1.0)

        log.info("task_worker_loop_ended")


task_worker = TaskWorker()
