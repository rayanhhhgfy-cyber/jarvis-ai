# ====================================================================
# JARVIS OMEGA — OS Agent
# ====================================================================
"""
Specialized OS Agent for executing local shell commands, managing system files,
controlling local background processes, and checking host OS configurations.
"""

from __future__ import annotations

import os
import time
import shutil
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from local_client.process_manager import local_process_manager
from shared.logger import get_logger

log = get_logger("agent_os")

class AgentOs:
    """
    Operating System interaction agent. Spawns processes, reads system details,
    performs administrative updates, and configures environments.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_os"
        self.agent_type = AgentType.OS

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Executes OS tasks such as shell commands, directory checks, or environment manipulation."""
        log.info("os_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "command")

            if action == "command" or action == "shell":
                result_data = await self._execute_command(task)
            elif action == "file_operation":
                result_data = await self._perform_file_operation(task)
            elif action == "env_info":
                result_data = await self._get_env_info()
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

    async def _execute_command(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs a native system shell command via the process manager."""
        cmd = task.payload.get("command")
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
            "success": exit_code == 0
        }

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

    async def _get_env_info(self) -> Dict[str, Any]:
        """Retrieves environment variables and platform details."""
        import platform
        return {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "cwd": os.getcwd(),
            "env_vars": dict(os.environ),
            "cpu_architecture": platform.machine()
        }
