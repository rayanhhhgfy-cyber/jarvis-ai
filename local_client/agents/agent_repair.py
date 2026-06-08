# ====================================================================
# JARVIS OMEGA — Repair Agent
# ====================================================================
"""
Specialized Repair Agent responsible for analyzing log stack traces, identifying
root causes of system failures, generating source file patches, and retesting.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_repair")

class AgentRepair:
    """
    Automated software repair and recovery agent. Analyzes error logs, proposes code
    patches, applies edits, and interfaces with the testing agent for validation.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_repair"
        self.agent_type = AgentType.REPAIR

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes repair commands such as patching syntax errors or solving failed tests."""
        log.info("repair_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "analyze")

            if action == "analyze":
                result_data = await self._analyze_error(task)
            elif action == "apply_patch":
                result_data = await self._apply_patch(task)
            else:
                raise ValueError(f"Unknown Repair action: {action}")

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
            log.error("repair_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _analyze_error(self, task: TaskDefinition) -> Dict[str, Any]:
        """Analyzes a traceback error log and isolates the line of code that triggered it."""
        traceback_str = task.payload.get("traceback")
        if not traceback_str:
            raise ValueError("traceback string is required for repair analysis")

        # Basic parse to extract file name and line number
        target_file = None
        line_number = None
        
        lines = traceback_str.split("\n")
        for line in reversed(lines):
            if "File " in line and ", line " in line:
                try:
                    # Example format: File "main.py", line 45, in some_func
                    parts = line.split('"')
                    target_file = parts[1]
                    line_part = parts[2].split(", line ")[1].split(",")[0]
                    line_number = int(line_part)
                    break
                except Exception:
                    continue

        return {
            "root_cause_analysis": "Exception thrown from trace file.",
            "isolated_file": target_file,
            "isolated_line": line_number,
            "proposed_fix": "Examine variables and check bound conditions."
        }

    async def _apply_patch(self, task: TaskDefinition) -> Dict[str, Any]:
        """Applies a specific code replacement patch to the isolated file path."""
        file_path = task.payload.get("file_path")
        target_text = task.payload.get("target_text")
        replacement_text = task.payload.get("replacement_text")

        if not file_path or not target_text or replacement_text is None:
            raise ValueError("file_path, target_text, and replacement_text are required to apply patch")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File to repair not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if target_text not in content:
            return {
                "success": False,
                "error": "Target content to patch was not found exactly in the file."
            }

        new_content = content.replace(target_text, replacement_text, 1)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "success": True,
            "file_patched": file_path,
            "timestamp": datetime.utcnow().isoformat()
        }
