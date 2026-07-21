# ====================================================================
# JARVIS OMEGA — Testing Agent
# ====================================================================
"""
Specialized Testing Agent for discovering, running, and generating report
insights for automated tests (pytest, unittest, etc.).
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_testing")


# Regex for the pytest "short test summary info" lines, e.g.:
#   FAILED backend/tests/test_main.py::test_health_endpoint - RuntimeError: ...
#   ERROR backend/tests/test_main.py::test_x - fixture 'y' not found
_PYTEST_SUMMARY_RE = re.compile(
    r"^(?P<status>FAILED|ERROR|PASSED|SKIPPED|XFAIL|XPASSED)\s+(?P<test>\S+)(?:\s+-\s+(?P<detail>.*))?$"
)
# Regex for the final "1 passed, 3 failed, 2 skipped in 4.5s" line.
_PYTEST_FINAL_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<outcome>passed|failed|errors|skipped|xfailed|xpassed|warnings)\b",
    re.IGNORECASE,
)


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

            if action in ("run", "pytest"):
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

    # ------------------------------------------------------------------
    # pytest runner with structured report
    # ------------------------------------------------------------------

    async def _run_pytest(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Run pytest with the project's existing config and parse the result.

        Strategy:
          1. Invoke ``python -m pytest <target> -v --tb=short``.
          2. Parse the per-test summary lines and the final outcome line.
          3. If pytest is invoked with ``--json-report`` available, prefer that.

        Returns a structured dict with ``passed``, ``failed``, ``errors``,
        ``skipped``, ``failures`` (list of {test, detail}), and raw outputs.
        """
        target_path = task.payload.get("target_path", ".")
        extra_args = task.payload.get("pytest_args", [])
        timeout = task.payload.get("timeout", task.timeout or 300)

        cmd: List[str] = [
            sys.executable, "-m", "pytest",
            target_path,
            "-v",
            "--tb=short",
            "--no-header",
            "-rA",  # report all outcomes in the summary section
        ]
        if isinstance(extra_args, list):
            cmd.extend(str(a) for a in extra_args)

        log.info("running_pytest_command", cmd=" ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=task.payload.get("cwd", os.getcwd()),
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "error": "pytest execution timed out",
                "timeout_limit": timeout,
                "summary": {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0},
                "failures": [],
            }
        except FileNotFoundError:
            return {
                "passed": False,
                "error": "pytest executable not found — is it installed in this environment?",
                "summary": {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0},
                "failures": [],
            }

        parsed = self._parse_pytest_output(proc.stdout, proc.stderr)
        parsed["exit_code"] = proc.returncode
        parsed["passed_overall"] = proc.returncode == 0
        parsed["stdout"] = proc.stdout
        parsed["stderr"] = proc.stderr
        parsed["target_path"] = target_path
        parsed["timestamp"] = datetime.utcnow().isoformat()
        return parsed

    @staticmethod
    def _parse_pytest_output(stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Walk the pytest stdout and extract:
          - per-test outcome counts
          - structured failure list (test name + detail)
          - the human-readable summary line
        """
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                  "xfailed": 0, "xpassed": 0, "warnings": 0}
        failures: List[Dict[str, Optional[str]]] = []
        summary_line = ""

        for line in stdout.splitlines():
            m = _PYTEST_SUMMARY_RE.match(line.strip())
            if m:
                status = m.group("status").lower()
                if status in counts:
                    counts[status] = counts.get(status, 0) + 1
                if status in ("failed", "error"):
                    failures.append({
                        "test": m.group("test"),
                        "detail": m.group("detail") or "",
                    })
                continue

            # final summary line typically reads like:
            # "=== 4 passed, 2 failed, 1 skipped in 6.23s ==="
            if "===" in line and ("passed" in line or "failed" in line or "error" in line):
                summary_line = line.strip()
                for fm in _PYTEST_FINAL_RE.finditer(line):
                    outcome = fm.group("outcome").lower()
                    if outcome in counts:
                        counts[outcome] = int(fm.group("count"))

        total = sum(counts.values())
        return {
            "summary": {
                "passed": counts["passed"],
                "failed": counts["failed"],
                "errors": counts["errors"],
                "skipped": counts["skipped"],
                "xfailed": counts["xfailed"],
                "xpassed": counts["xpassed"],
                "total": total,
            },
            "summary_line": summary_line,
            "failures": failures[:200],   # cap so we don't blow up the result envelope
        }

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def _discover_tests(self, task: TaskDefinition) -> Dict[str, Any]:
        """Discovers existing test files matching typical pytest conventions."""
        search_dir = task.payload.get("search_dir", ".")
        test_files: List[str] = []

        try:
            for root, _, files in os.walk(search_dir):
                # Skip common noise directories.
                if any(part in {"__pycache__", ".git", "node_modules", ".venv", "venv"}
                       for part in Path(root).parts):
                    continue
                for file in files:
                    if (file.startswith("test_") or file.endswith("_test.py")) and file.endswith(".py"):
                        test_files.append(os.path.join(root, file))
        except Exception as walk_err:
            log.warning("test_discovery_walk_failed", error=str(walk_err))

        return {
            "search_directory": os.path.abspath(search_dir),
            "discovered_test_files_count": len(test_files),
            "test_files": test_files,
        }
