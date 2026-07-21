# ====================================================================
# JARVIS OMEGA — Repair Agent
# ====================================================================
"""
Specialized Repair Agent responsible for analyzing log stack traces, identifying
root causes of system failures, generating source file patches, and retesting.
"""

from __future__ import annotations

import os
import re
import time
import traceback as tb_module
from typing import Dict, Any, List, Optional
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_repair")


# Pre-compiled Python traceback frame parser.
# Matches lines like:   File "backend/main.py", line 42, in get_health
_PY_FRAME_RE = re.compile(
    r'^\s*File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\S+))?'
)
# Final exception line, e.g.  "ValueError: bad input" or "module.X.YError: detail"
_PY_EXC_LINE_RE = re.compile(
    r'^(?P<etype>[A-Za-z_][\w\.]*(?:Error|Exception|Warning))\s*:\s*(?P<detail>.*)$'
)


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
            err_msg = f"{str(e)}\n{tb_module.format_exc()}"
            log.error("repair_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    # ------------------------------------------------------------------
    # Traceback analysis — structured parser (no more split('"'))
    # ------------------------------------------------------------------

    async def _analyze_error(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Parse a Python traceback string into a structured diagnosis.

        Returns:
          - ``isolated_file`` / ``isolated_line`` / ``isolated_function``:
            deepest frame (closest to the failure) extracted from the trace.
          - ``exception_type`` / ``exception_detail``: final raise line.
          - ``all_frames``: list of every frame parsed, oldest first.
          - ``root_cause_analysis``: short human-readable summary.
          - ``proposed_fix``: heuristic next-step guidance.
        """
        traceback_str = task.payload.get("traceback")
        if not traceback_str:
            raise ValueError("traceback string is required for repair analysis")

        frames = self._parse_python_traceback(traceback_str)
        exc = self._parse_exception_line(traceback_str)

        deepest = frames[-1] if frames else {}

        proposed = self._propose_fix(deepest, exc)

        return {
            "root_cause_analysis": (
                f"Exception originated in {deepest.get('file', '?')}"
                f":{deepest.get('line', '?')} "
                f"in {deepest.get('function', '<module>')}."
                if deepest
                else "No Python traceback frames could be parsed."
            ),
            "isolated_file": deepest.get("file"),
            "isolated_line": deepest.get("line"),
            "isolated_function": deepest.get("function"),
            "exception_type": exc.get("type"),
            "exception_detail": exc.get("detail"),
            "all_frames": frames,
            "proposed_fix": proposed,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _parse_python_traceback(text: str) -> List[Dict[str, Any]]:
        """Walk every line; extract every ``File "...", line N, in FUNC`` frame."""
        frames: List[Dict[str, Any]] = []
        for raw in text.splitlines():
            m = _PY_FRAME_RE.match(raw)
            if not m:
                continue
            try:
                line_no = int(m.group("line"))
            except (TypeError, ValueError):
                continue
            frames.append({
                "file": m.group("file"),
                "line": line_no,
                "function": m.group("func") or "",
            })
        return frames

    @staticmethod
    def _parse_exception_line(text: str) -> Dict[str, Optional[str]]:
        """Extract the final ``ExceptionType: detail`` line if present."""
        for raw in reversed(text.splitlines()):
            m = _PY_EXC_LINE_RE.match(raw.strip())
            if m:
                return {"type": m.group("etype"), "detail": m.group("detail")}
        return {"type": None, "detail": None}

    @staticmethod
    def _propose_fix(frame: Dict[str, Any], exc: Dict[str, Optional[str]]) -> str:
        """Heuristic next-step guidance based on the parsed exception type."""
        et = (exc.get("type") or "").lower()
        if not frame and not exc:
            return "No structured data — manual investigation required."
        if "import" in et or "module" in et:
            return "Missing or misnamed import. Verify the module is installed and the path is correct."
        if "name" in et:
            return "Undefined name. Check for typos and that the symbol is imported."
        if "attribute" in et:
            return "Attribute access on None or wrong type. Add a type/None guard."
        if "key" in et or "index" in et:
            return "Container access failure. Add an existence / bounds check before access."
        if "type" in et:
            return "Type mismatch. Inspect argument types at the call site."
        if "value" in et:
            return "Invalid value. Validate inputs at the boundary of the function."
        if "zero" in et:
            return "Division by zero. Guard the denominator."
        if "file" in et or "notfound" in et:
            return "File not found. Verify the path and current working directory."
        if "permission" in et:
            return "Permission denied. Check file mode and that JARVIS has access rights."
        return "Examine local variables at the isolated frame and reproduce the failure."

    # ------------------------------------------------------------------
    # Patch application
    # ------------------------------------------------------------------

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
                "error": "Target content to patch was not found exactly in the file.",
                "file_path": file_path,
            }

        new_content = content.replace(target_text, replacement_text, 1)

        # Capture a tiny diff for the audit trail.
        diff_preview = self._simple_diff_preview(target_text, replacement_text)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "success": True,
            "file_patched": file_path,
            "diff_preview": diff_preview,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _simple_diff_preview(old: str, new: str, max_chars: int = 200) -> str:
        """Tiny unified-diff-style preview for logs."""
        old_short = old if len(old) <= max_chars else old[:max_chars] + "..."
        new_short = new if len(new) <= max_chars else new[:max_chars] + "..."
        return f"--- \n- {old_short}\n+++ \n+ {new_short}"
