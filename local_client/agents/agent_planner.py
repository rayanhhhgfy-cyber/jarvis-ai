# ====================================================================
# JARVIS OMEGA — Planner Agent
# ====================================================================
"""
Specialized Planner Agent responsible for breaking down high-level user tasks
into organized dependency graphs, ordering steps, and plotting pipelines.

Phase 4: real LLM-driven decomposition with JSON-validated output and a
deterministic template fallback for offline / LLM-failure cases.
"""

from __future__ import annotations

import json
import time
import traceback
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_planner")


_PLANNER_SYSTEM_PROMPT = (
    "You are the JARVIS Planner module. Decompose Sir's goal into an ordered "
    "list of concrete subtasks that other JARVIS agents can execute.\n\n"
    "Output STRICT JSON only — no prose, no markdown fences. The shape must be:\n"
    "{\n"
    '  "steps": [\n'
    '    {"title": string, "description": string, "agent_type": string, "payload": {}}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- agent_type must be one of: orchestrator, code, document, video, os, "
    "vision, monitor, deployment, testing, repair, memory, security, browser, "
    "research, planner, worker.\n"
    "- 2-8 steps total. Each step must be independently executable.\n"
    "- Prefer ordering that lets later steps build on earlier ones.\n"
    "- payload can carry any JSON the agent understands (action, file, command...).\n"
    "- NEVER wrap output in ```json fences. Output raw JSON only."
)

_VALID_AGENT_TYPES = {
    "orchestrator", "code", "document", "video", "os",
    "vision", "monitor", "deployment", "testing", "repair",
    "memory", "security", "browser", "research", "planner", "worker",
}


class AgentPlanner:
    """
    Project planner agent. Decomposes master user commands into structured
    subtasks and designs the execution sequence.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_planner"
        self.agent_type = AgentType.PLANNER

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes planning commands like task scheduling and step decomposition."""
        log.info("planner_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "decompose")

            if action in ("decompose", "plan"):
                result_data = await self._decompose_goals(task)
            else:
                raise ValueError(f"Unknown Planner action: {action}")

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
            log.error("planner_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    # ------------------------------------------------------------------
    # Decomposition
    # ------------------------------------------------------------------

    async def _decompose_goals(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Break a composite goal down into concrete execution subtasks.

        Tries the LLM first; on any failure (no key, network error, malformed
        JSON, empty response) falls back to the deterministic template so the
        planner agent never hard-fails.
        """
        goal = task.payload.get("goal")
        if not goal:
            raise ValueError("goal description is required for decomposition")

        log.info("planning_decomposition_steps", goal=goal)

        steps: Optional[List[Dict[str, Any]]] = None
        decomposition_source = "template"
        llm_error: Optional[str] = None

        try:
            steps = await self._llm_decompose(goal, task)
            decomposition_source = "llm"
        except Exception as llm_err:
            llm_error = str(llm_err)
            log.warning("planner_llm_failed_using_template", error=llm_error)

        if not steps:
            steps = self._template_decompose(goal)
            decomposition_source = "template"

        # Final sanity: validate agent_type on every step.
        for step in steps:
            at = step.get("agent_type", "worker")
            if at not in _VALID_AGENT_TYPES:
                log.warning("planner_step_invalid_agent_type", got=at, coercing="worker")
                step["agent_type"] = "worker"

        return {
            "master_goal": goal,
            "steps_count": len(steps),
            "subtasks": steps,
            "ordered": True,
            "decomposition_source": decomposition_source,
            "llm_error": llm_error,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def _llm_decompose(self, goal: str, task: TaskDefinition) -> List[Dict[str, Any]]:
        """
        Call llm_service with the planner prompt and parse strict JSON output.
        Raises on any failure — the caller will use the template fallback.
        """
        from backend.services.llm_service import llm_service

        # Allow callers to pass extra context (constraints, prior art, files…)
        extra_context = task.payload.get("context", "")
        user_msg = f"GOAL: {goal}"
        if extra_context:
            user_msg += f"\n\nCONTEXT:\n{extra_context}"

        raw = await llm_service.get_response(
            user_message=user_msg,
            system_instructions=_PLANNER_SYSTEM_PROMPT,
            inject_memory=False,
        )

        if not raw:
            raise RuntimeError("LLM returned empty response")

        # Strip accidental ```json fences.
        cleaned = self._strip_code_fences(raw).strip()
        # Some models add trailing commentary after the JSON; cut at first
        # unbalanced closing brace using a tolerant parser.
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to salvage by extracting the largest {...} block.
            salvaged = self._extract_json_block(cleaned)
            if salvaged is None:
                raise RuntimeError(f"LLM did not return valid JSON: {cleaned[:200]}")
            parsed = json.loads(salvaged)

        steps = parsed.get("steps") if isinstance(parsed, dict) else None
        if not isinstance(steps, list) or not steps:
            raise RuntimeError("LLM JSON missing 'steps' array")

        normalized: List[Dict[str, Any]] = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            normalized.append({
                "title": str(s.get("title", "Untitled step"))[:200],
                "description": str(s.get("description", ""))[:1000],
                "agent_type": str(s.get("agent_type", "worker")).lower(),
                "payload": s.get("payload") if isinstance(s.get("payload"), dict) else {},
            })
        if not normalized:
            raise RuntimeError("LLM JSON 'steps' contained no valid entries")
        return normalized

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove surrounding ```json ... ``` fences if present."""
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines)
        return text

    @staticmethod
    def _extract_json_block(text: str) -> Optional[str]:
        """Return the largest balanced {...} substring of text, or None."""
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    @staticmethod
    def _template_decompose(goal: str) -> List[Dict[str, Any]]:
        """Deterministic fallback used when the LLM is unavailable or malformed."""
        return [
            {
                "title": "Analyze and audit",
                "description": f"Gather prerequisites and context for goal: {goal}",
                "agent_type": "research",
                "payload": {"topic": goal},
            },
            {
                "title": "Implement changes",
                "description": "Produce the code / artefacts required by the goal.",
                "agent_type": "code",
                "payload": {"action": "write"},
            },
            {
                "title": "Verify changes",
                "description": "Run lint, type-check and tests on the produced artefacts.",
                "agent_type": "testing",
                "payload": {"action": "run"},
            },
        ]
