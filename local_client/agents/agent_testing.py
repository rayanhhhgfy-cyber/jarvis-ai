# ====================================================================
# JARVIS OMEGA — Testing Agent
# ====================================================================
"""
Specialized Testing Agent for discovering, running, and generating report
insights for automated tests (pytest, unittest, etc.).
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

log = get_logger("agent_testing")

class AgentTesting:
    """
    Automated QA and testing agent. Executes test suites, analyzes failure stack traces,
    computes coverage states, and generates syntax-validated tests.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_testing"
        self.agent_type = AgentType.TESTING

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Runs testing suites or executes targeted unit tests on user workspace."""
        log.info("testing_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "run")

            if action == "run" or action == "pytest":
                result_data = await self._run_pytest(task)
            elif action == "discover":
                result_data = await self._discover_tests(task)
            else:
                raise ValueError(f"Unknown Testing action: {action}")

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
            log.error("testing_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _run_pytest(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs pytest on the specified directory or test file path."""
        target_path = task.payload.get("target_path", ".")
        
        # Build pytest execution command
        cmd = [sys.executable, "-m", "pytest", target_path, "-v"]
        
        log.info("running_pytest_command", cmd=" ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=task.timeout
            )
            
            # Simple parsing of stdout to determine success
            passed = proc.returncode == 0
            
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "passed": passed,
                "summary": "Tests executed successfully." if passed else "Some tests failed or exited with error."
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "error": "pytest execution timed out",
                "timeout_limit": task.timeout
            }

    async def _discover_tests(self, task: TaskDefinition) -> Dict[str, Any]:
        """Discovers existing test files matching typical pytest conventions."""
        search_dir = task.payload.get("search_dir", ".")
        test_files = []

        for root, _, files in os.walk(search_dir):
            for file in files:
                if (file.startswith("test_") or file.endswith("_test.py")) and file.endswith(".py"):
                    test_files.append(os.path.join(root, file))

        return {
            "search_directory": os.path.abspath(search_dir),
            "discovered_test_files_count": len(test_files),
            "test_files": test_files
        }
