# ====================================================================
# JARVIS OMEGA — Code Agent
# ====================================================================
"""
Specialized Code Agent responsible for automated code generation, refactoring,
debugging, analysis, and syntax validation.
"""

from __future__ import annotations

import os
import sys
import time
import subprocess
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_code")

class AgentCode:
    """
    Automated software engineering agent. Performs filesystem edits, code execution,
    refactoring, linting, and testing on behalf of Sir.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_code"
        self.agent_type = AgentType.CODE

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """
        Processes code-specific tasks such as modifying files, running scripts,
        or linting/verifying syntax.
        """
        log.info("code_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()
        
        try:
            action = task.payload.get("action", "run")
            
            if action == "write":
                result_data = await self._write_code(task)
            elif action == "read":
                result_data = await self._read_code(task)
            elif action == "lint":
                result_data = await self._lint_code(task)
            elif action == "run" or action == "execute":
                result_data = await self._run_code(task)
            else:
                raise ValueError(f"Unknown action for Code Agent: {action}")

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
            log.error("code_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _write_code(self, task: TaskDefinition) -> Dict[str, Any]:
        """Writes or modifies a file on the local filesystem."""
        path = task.payload.get("file_path")
        content = task.payload.get("content")
        if not path or content is None:
            raise ValueError("file_path and content are required for code write action")

        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "status": "success",
            "file_path": path,
            "bytes_written": len(content),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _read_code(self, task: TaskDefinition) -> Dict[str, Any]:
        """Reads code from a file."""
        path = task.payload.get("file_path")
        if not path:
            raise ValueError("file_path is required for code read action")

        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "status": "success",
            "file_path": path,
            "content": content,
            "lines": len(content.splitlines())
        }

    async def _lint_code(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs syntax verification (py_compile for Python, custom checks for others)."""
        path = task.payload.get("file_path")
        if not path:
            raise ValueError("file_path is required for lint action")

        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        if path.endswith(".py"):
            # Simple python syntax check
            cmd = [sys.executable, "-m", "py_compile", path]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return {
                    "valid": False,
                    "error": proc.stderr,
                    "exit_code": proc.returncode
                }
            return {"valid": True, "details": "Python compilation check passed"}

        return {"valid": True, "details": "Linting not implemented for this file type"}

    async def _run_code(self, task: TaskDefinition) -> Dict[str, Any]:
        """Executes a code block or script and captures output."""
        code = task.payload.get("code")
        file_path = task.payload.get("file_path")

        if not code and not file_path:
            raise ValueError("Either code block or file_path must be provided to run code")

        temp_file = False
        if code:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tf:
                tf.write(code.encode("utf-8"))
                file_path = tf.name
                temp_file = True

        try:
            cmd = [sys.executable, file_path]
            # Execute subprocess with timeout
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=task.timeout
            )
            
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "completed": True
            }
        finally:
            if temp_file and file_path and os.path.exists(file_path):
                os.remove(file_path)
