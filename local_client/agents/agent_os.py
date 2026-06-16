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
import shutil
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from local_client.process_manager import local_process_manager
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

            if action == "get_vitals" or action == "env_info":
                result_data = await self._get_system_vitals(task)
            elif action == "manage_process":
                result_data = await self._manage_process(task)
            elif action == "run_shell" or action == "command" or action == "shell":
                result_data = await self._run_shell_command(task)
            elif action == "file_operation":
                result_data = await self._perform_file_operation(task)
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
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            "cwd": os.getcwd(),
            "env_vars": dict(os.environ),
            "cpu_architecture": platform.machine()
        }

    async def _manage_process(self, task: TaskDefinition) -> Dict[str, Any]:
        process_name = task.payload.get("process_name")
        sub_action = task.payload.get("sub_action", "list")

        if sub_action == "list":
            procs = [{"pid": p.info['pid'], "name": p.info['name']} for p in psutil.process_iter(['pid', 'name']) if not process_name or process_name in p.info['name']]
            return {"processes": procs[:20]}
        elif sub_action == "terminate":
            pid = task.payload.get("pid")
            if pid:
                p = psutil.Process(pid)
                p.terminate()
                return {"status": "terminated", "pid": pid}
        return {"status": "unsupported_sub_action"}

    async def _run_shell_command(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs a native system shell command via the process manager."""
        cmd = task.payload.get("command") or task.payload.get("cmd")
        if not cmd:
            raise ValueError("command string is required for OS command action")

        cwd = task.payload.get("cwd")
        env = task.payload.get("env")

        proc_id = f"os_{task.task_id}"
        success, msg = await local_process_manager.spawn_process(proc_id, cmd, cwd=cwd, env=env)
        if not success:
            raise RuntimeError(f"Failed to spawn system command: {msg}")

        exit_code, stdout, stderr = await local_process_manager.wait_process(proc_id)

        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "success": exit_code == 0,
            "output": stdout # for backward compatibility
        }

    async def _execute_command(self, task: TaskDefinition) -> Dict[str, Any]:
        """Backward compatibility alias for _run_shell_command."""
        return await self._run_shell_command(task)

    async def _perform_file_operation(self, task: TaskDefinition) -> Dict[str, Any]:
        """Performs administrative file operations (copy, move, delete, create directory)."""
        op_type = task.payload.get("op_type")  # cp, mv, rm, mkdir, rmdir
        src = task.payload.get("src")
        dst = task.payload.get("dst")

        if not op_type:
            raise ValueError("op_type is required for file_operation action")

        if op_type == "mkdir":
            if not dst:
                raise ValueError("dst directory path required for mkdir")
            os.makedirs(dst, exist_ok=True)
            return {"status": "directory_created", "path": dst}

        elif op_type == "rm":
            if not src:
                raise ValueError("src path required for rm")
            if os.path.isdir(src):
                shutil.rmtree(src)
                return {"status": "directory_deleted", "path": src}
            else:
                os.remove(src)
                return {"status": "file_deleted", "path": src}

        elif op_type == "cp":
            if not src or not dst:
                raise ValueError("src and dst are required for cp")
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return {"status": "copied", "src": src, "dst": dst}

        elif op_type == "mv":
            if not src or not dst:
                raise ValueError("src and dst are required for mv")
            shutil.move(src, dst)
            return {"status": "moved", "src": src, "dst": dst}

        else:
            raise ValueError(f"Unsupported file operation type: {op_type}")
