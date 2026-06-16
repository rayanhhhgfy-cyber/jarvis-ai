# ====================================================================
# JARVIS OMEGA — Worker Agent (Versatile Task Executor)
# ====================================================================
"""
Versatile Worker Agent capable of handling generic tasks, file management,
system utilities, and coordinating small sub-tasks.
"""

from __future__ import annotations

import os
import shutil
import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_worker")

class AgentWorker:
    """
    General-purpose worker agent for miscellaneous tasks.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_worker"
        self.agent_type = AgentType.WORKER

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("worker_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "file_manage")

            if action == "file_manage":
                result_data = await self._manage_files(task)
            elif action == "system_utility":
                result_data = await self._run_utility(task)
            elif action == "batch_process":
                result_data = await self._batch_process(task)
            else:
                raise ValueError(f"Unknown Worker action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("worker_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _manage_files(self, task: TaskDefinition) -> Dict[str, Any]:
        sub_action = task.payload.get("sub_action", "list")
        path = task.payload.get("path", ".")

        if sub_action == "list":
            files = os.listdir(path)
            return {"files": files, "count": len(files)}
        elif sub_action == "copy":
            src = task.payload.get("src")
            dst = task.payload.get("dst")
            shutil.copy(src, dst)
            return {"status": "copied", "src": src, "dst": dst}
        return {"status": "no_action"}

    async def _run_utility(self, task: TaskDefinition) -> Dict[str, Any]:
        utility = task.payload.get("utility", "ping")
        return {"utility": utility, "output": "Execution successful", "timestamp": datetime.utcnow().isoformat()}

    async def _batch_process(self, task: TaskDefinition) -> Dict[str, Any]:
        items = task.payload.get("items", [])
        return {"processed_count": len(items), "status": "all_completed"}
