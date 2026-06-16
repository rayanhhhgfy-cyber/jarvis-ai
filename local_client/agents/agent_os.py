# ====================================================================
# JARVIS OMEGA — OS Agent
# ====================================================================
"""
Specialized OS Agent responsible for system management, process control,
hardware monitoring, and desktop automation.
"""

from __future__ import annotations

import os
import psutil
import time
import traceback
import platform
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_os")

class AgentOs:
    """
    Operating System interaction agent. Manages local hardware and processes.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_os"
        self.agent_type = AgentType.OS

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("os_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "get_vitals")

            if action == "get_vitals":
                result_data = await self._get_system_vitals(task)
            elif action == "manage_process":
                result_data = await self._manage_process(task)
            elif action == "run_shell":
                result_data = await self._run_shell_command(task)
            else:
                raise ValueError(f"Unknown OS action: {action}")

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
            log.error("os_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _get_system_vitals(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "cpu_count": psutil.cpu_count(),
            "cpu_usage_percent": psutil.cpu_percent(interval=1),
            "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "disk_usage_percent": psutil.disk_usage('/').percent,
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat()
        }

    async def _manage_process(self, task: TaskDefinition) -> Dict[str, Any]:
        process_name = task.payload.get("process_name")
        sub_action = task.payload.get("sub_action", "list")

        if sub_action == "list":
            procs = [{"pid": p.info['pid'], "name": p.info['name']} for p in psutil.process_iter(['pid', 'name']) if process_name in p.info['name']]
            return {"processes": procs[:10]}
        return {"status": "unsupported_sub_action"}

    async def _run_shell_command(self, task: TaskDefinition) -> Dict[str, Any]:
        import subprocess
        command = task.payload.get("command") or task.payload.get("cmd")
        proc = subprocess.run(command, shell=True, capture_output=True, text=True)
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "return_code": proc.returncode,
            "output": proc.stdout # for backward compatibility
        }

    async def _execute_command(self, task: TaskDefinition) -> Dict[str, Any]:
        """Backward compatibility alias for _run_shell_command."""
        return await self._run_shell_command(task)
