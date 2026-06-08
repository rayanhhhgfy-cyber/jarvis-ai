# ====================================================================
# JARVIS OMEGA — Mega Goal Executor (1000+ Step Engine)
# ====================================================================
"""
Goal-driven execution loop capable of handling extremely complex,
multi-phase goals with 1000+ steps.

Features:
- Hierarchical decomposition (Goal → Phases → Steps)
- Checkpoint/resume to disk (survives restarts)
- Adaptive re-planning every N steps
- Failure recovery with alternative approaches
- Live progress streaming via WebSocket
- Cancellation support
- Parallel step execution within phases (optional)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants import TaskStatus
from shared.logger import get_logger
from shared.models import TaskResult

log = get_logger("goal_executor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MAX_ITERATIONS = 1000
DEFAULT_TIMEOUT_SECONDS = 7200  # 2 hours
REPLAN_INTERVAL = 10  # re-evaluate plan every N steps
MAX_STEP_RETRIES = 3
MAX_ALTERNATIVE_APPROACHES = 3
CHECKPOINT_DIR = Path("./storage/goals")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _safe_json_parse(text: str) -> Optional[dict]:
    """Extract the first JSON object from LLM output."""
    clean = text.strip()
    # Strip markdown code fences
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Goal State (persisted to disk)
# ---------------------------------------------------------------------------

class GoalState:
    """Serializable state for a running goal."""

    def __init__(self, goal_id: str, goal: str, **kwargs):
        self.goal_id = goal_id
        self.goal = goal
        self.user_id = kwargs.get("user_id", "default")
        self.status = kwargs.get("status", "running")  # running | paused | completed | failed | cancelled
        self.max_iterations = kwargs.get("max_iterations", DEFAULT_MAX_ITERATIONS)
        self.timeout_seconds = kwargs.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        self.context = kwargs.get("context", {})

        # Hierarchical plan
        self.phases: List[Dict[str, Any]] = kwargs.get("phases", [])
        self.current_phase_idx: int = kwargs.get("current_phase_idx", 0)
        self.current_step_idx: int = kwargs.get("current_step_idx", 0)

        # Flat execution log
        self.execution_log: List[Dict[str, Any]] = kwargs.get("execution_log", [])
        self.total_steps_executed: int = kwargs.get("total_steps_executed", 0)
        self.total_steps_succeeded: int = kwargs.get("total_steps_succeeded", 0)
        self.total_steps_failed: int = kwargs.get("total_steps_failed", 0)

        # Timing
        self.started_at = kwargs.get("started_at", _now_iso())
        self.completed_at = kwargs.get("completed_at", None)
        self.elapsed_seconds = kwargs.get("elapsed_seconds", 0.0)

        # Result
        self.summary = kwargs.get("summary", "")
        self.error = kwargs.get("error", None)

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "goal": self.goal,
            "user_id": self.user_id,
            "status": self.status,
            "max_iterations": self.max_iterations,
            "timeout_seconds": self.timeout_seconds,
            "context": self.context,
            "phases": self.phases,
            "current_phase_idx": self.current_phase_idx,
            "current_step_idx": self.current_step_idx,
            "execution_log": self.execution_log[-50:],  # Keep last 50 for serialization
            "total_steps_executed": self.total_steps_executed,
            "total_steps_succeeded": self.total_steps_succeeded,
            "total_steps_failed": self.total_steps_failed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": self.elapsed_seconds,
            "summary": self.summary,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalState":
        return cls(**data)

    def save(self) -> None:
        """Persist state to disk."""
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        path = CHECKPOINT_DIR / f"{self.goal_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, goal_id: str) -> Optional["GoalState"]:
        """Load state from disk."""
        path = CHECKPOINT_DIR / f"{goal_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        return None

    @property
    def progress_percent(self) -> float:
        """Calculate overall progress percentage."""
        if not self.phases:
            if self.max_iterations > 0:
                return min(100.0, (self.total_steps_executed / self.max_iterations) * 100)
            return 0.0

        total_steps = sum(len(p.get("steps", [])) for p in self.phases)
        if total_steps == 0:
            return 0.0
        completed = sum(
            1 for p in self.phases
            for s in p.get("steps", [])
            if s.get("status") in ("completed", "skipped")
        )
        return min(100.0, (completed / total_steps) * 100)

    @property
    def current_phase_name(self) -> str:
        if 0 <= self.current_phase_idx < len(self.phases):
            return self.phases[self.current_phase_idx].get("name", f"Phase {self.current_phase_idx + 1}")
        return "Unknown"


# ---------------------------------------------------------------------------
# Mega Goal Executor
# ---------------------------------------------------------------------------

class GoalExecutor:
    """
    Executes complex, multi-phase goals with 1000+ step support.
    Decomposes goals hierarchically, checkpoints progress, and
    adaptively re-plans as execution progresses.
    """

    def __init__(self):
        self._running_goals: Dict[str, GoalState] = {}
        self._cancelled: set = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_goal(
        self,
        goal: str,
        user_id: str = "default",
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a complex goal with hierarchical decomposition.

        Args:
            goal: The high-level goal to achieve
            user_id: User identifier
            max_iterations: Maximum total step iterations (default 1000)
            timeout_seconds: Maximum total execution time (default 7200s / 2h)
            context: Optional initial context

        Returns:
            Full result dict with goal_id, success, phases, log, summary
        """
        goal_id = f"goal_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

        state = GoalState(
            goal_id=goal_id,
            goal=goal,
            user_id=user_id,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            context=context or {},
        )
        self._running_goals[goal_id] = state

        log.info("mega_goal_started", goal_id=goal_id, goal=goal[:120], max_iter=max_iterations)

        try:
            # Phase 1: Decompose goal into phases and steps
            await self._decompose_goal(state)
            state.save()

            # Phase 2: Execute each phase
            await self._execute_phases(state)

        except asyncio.CancelledError:
            state.status = "cancelled"
            state.summary = "Goal was cancelled by user."
            log.info("goal_cancelled", goal_id=goal_id)
        except Exception as e:
            state.status = "failed"
            state.error = str(e)
            state.summary = f"Goal failed: {str(e)}"
            log.error("goal_execution_error", goal_id=goal_id, error=str(e), tb=traceback.format_exc())
        finally:
            if state.status == "running":
                state.status = "completed"
            state.completed_at = _now_iso()
            state.save()
            self._running_goals.pop(goal_id, None)
            self._cancelled.discard(goal_id)

        return state.to_dict()

    async def resume_goal(self, goal_id: str) -> Dict[str, Any]:
        """Resume a checkpointed goal from where it left off."""
        state = GoalState.load(goal_id)
        if not state:
            return {"error": f"No checkpoint found for goal {goal_id}"}

        if state.status not in ("running", "paused"):
            return {"error": f"Goal is in '{state.status}' state, cannot resume"}

        log.info("goal_resuming", goal_id=goal_id, phase=state.current_phase_idx, step=state.current_step_idx)
        state.status = "running"
        self._running_goals[goal_id] = state

        try:
            await self._execute_phases(state)
        except asyncio.CancelledError:
            state.status = "cancelled"
        except Exception as e:
            state.status = "failed"
            state.error = str(e)
        finally:
            if state.status == "running":
                state.status = "completed"
            state.completed_at = _now_iso()
            state.save()
            self._running_goals.pop(goal_id, None)

        return state.to_dict()

    def cancel_goal(self, goal_id: str) -> Dict[str, Any]:
        """Cancel a running goal."""
        self._cancelled.add(goal_id)
        state = self._running_goals.get(goal_id)
        if state:
            state.status = "cancelled"
            state.save()
            return {"status": "cancelled", "goal_id": goal_id}
        return {"status": "not_found", "goal_id": goal_id}

    def get_goal_progress(self, goal_id: str) -> Optional[Dict[str, Any]]:
        """Get progress of a running or checkpointed goal."""
        state = self._running_goals.get(goal_id)
        if not state:
            state = GoalState.load(goal_id)
        if not state:
            return None

        return {
            "goal_id": state.goal_id,
            "goal": state.goal,
            "status": state.status,
            "progress_percent": round(state.progress_percent, 1),
            "current_phase": state.current_phase_name,
            "current_phase_idx": state.current_phase_idx,
            "total_phases": len(state.phases),
            "total_steps_executed": state.total_steps_executed,
            "total_steps_succeeded": state.total_steps_succeeded,
            "total_steps_failed": state.total_steps_failed,
            "elapsed_seconds": state.elapsed_seconds,
            "phases": [
                {
                    "name": p.get("name", ""),
                    "description": p.get("description", ""),
                    "step_count": len(p.get("steps", [])),
                    "completed": sum(1 for s in p.get("steps", []) if s.get("status") == "completed"),
                    "failed": sum(1 for s in p.get("steps", []) if s.get("status") == "failed"),
                }
                for p in state.phases
            ],
            "recent_log": state.execution_log[-10:],
        }

    def get_running_goals(self) -> Dict[str, Any]:
        """Return all currently running goals."""
        return {
            gid: {
                "goal": s.goal,
                "status": s.status,
                "progress": round(s.progress_percent, 1),
                "phase": s.current_phase_name,
                "steps_executed": s.total_steps_executed,
            }
            for gid, s in self._running_goals.items()
        }

    def list_checkpointed_goals(self) -> List[Dict[str, Any]]:
        """List all goals with checkpoints on disk."""
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        results = []
        for path in CHECKPOINT_DIR.glob("goal_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "goal_id": data.get("goal_id"),
                    "goal": data.get("goal", "")[:100],
                    "status": data.get("status"),
                    "progress": round(GoalState.from_dict(data).progress_percent, 1),
                    "started_at": data.get("started_at"),
                    "completed_at": data.get("completed_at"),
                })
            except Exception:
                pass
        return sorted(results, key=lambda x: x.get("started_at", ""), reverse=True)

    # ------------------------------------------------------------------
    # Goal Decomposition
    # ------------------------------------------------------------------

    async def _decompose_goal(self, state: GoalState) -> None:
        """Use LLM to decompose a complex goal into phases and steps."""
        from backend.services.llm_service import llm_service

        log.info("decomposing_goal", goal_id=state.goal_id)

        system_prompt = (
            "You are J.A.R.V.I.S., an elite AI execution planner. "
            "Sir has given you a complex goal. You must decompose it into an execution plan.\n\n"
            "Output ONLY valid JSON with this structure:\n"
            "{\n"
            '  "phases": [\n'
            "    {\n"
            '      "name": "Phase name",\n'
            '      "description": "What this phase accomplishes",\n'
            '      "steps": [\n'
            '        {"action": "Specific action description", "command_hint": "optional command hint"}\n'
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Create 2-20 phases depending on complexity\n"
            "- Each phase should have 1-50 steps\n"
            "- Steps should be concrete, executable actions\n"
            "- Order phases logically (dependencies first)\n"
            "- Be thorough — break the goal into EVERY necessary step\n"
            "- command_hint can reference: desktop_*, browser_*, search_web|, "
            "download_file|, PowerShell commands, generate_image|, agent_|, etc.\n"
        )

        context_str = f"\nContext: {json.dumps(state.context)}" if state.context else ""
        user_msg = f"Decompose this goal into a detailed execution plan:\n\n{state.goal}{context_str}"

        response = await llm_service.get_response(
            user_message=user_msg,
            system_instructions=system_prompt,
            inject_memory=True,
        )

        plan = _safe_json_parse(response)
        if plan and "phases" in plan:
            state.phases = []
            for pi, phase_data in enumerate(plan["phases"][:20]):
                phase = {
                    "name": phase_data.get("name", f"Phase {pi + 1}"),
                    "description": phase_data.get("description", ""),
                    "steps": [],
                    "status": "pending",
                }
                for si, step_data in enumerate(phase_data.get("steps", [])[:50]):
                    phase["steps"].append({
                        "action": step_data.get("action", f"Step {si + 1}"),
                        "command_hint": step_data.get("command_hint", ""),
                        "status": "pending",
                        "retries": 0,
                        "output": "",
                        "error": "",
                    })
                state.phases.append(phase)

            total_steps = sum(len(p["steps"]) for p in state.phases)
            log.info("goal_decomposed",
                     goal_id=state.goal_id,
                     phases=len(state.phases),
                     total_steps=total_steps)
        else:
            # Fallback: single phase with iterative execution
            log.warning("goal_decomposition_failed_using_fallback", goal_id=state.goal_id)
            state.phases = [{
                "name": "Iterative Execution",
                "description": "Executing goal step by step",
                "steps": [{"action": state.goal, "command_hint": "", "status": "pending", "retries": 0, "output": "", "error": ""}],
                "status": "pending",
            }]

        await self._emit_progress(state, "Goal decomposed into execution plan")

    # ------------------------------------------------------------------
    # Phase Execution
    # ------------------------------------------------------------------

    async def _execute_phases(self, state: GoalState) -> None:
        """Execute all phases sequentially."""
        start_time = time.time() - state.elapsed_seconds

        while state.current_phase_idx < len(state.phases):
            if self._is_cancelled(state.goal_id):
                state.status = "cancelled"
                return

            # Timeout check
            state.elapsed_seconds = time.time() - start_time
            if state.elapsed_seconds > state.timeout_seconds:
                state.status = "failed"
                state.error = f"Goal timed out after {state.elapsed_seconds:.0f}s"
                log.warning("goal_timeout", goal_id=state.goal_id)
                return

            # Max iterations check
            if state.total_steps_executed >= state.max_iterations:
                state.status = "failed"
                state.error = f"Reached max iterations ({state.max_iterations})"
                log.warning("goal_max_iterations", goal_id=state.goal_id)
                return

            phase = state.phases[state.current_phase_idx]
            phase["status"] = "running"

            log.info("phase_starting",
                     goal_id=state.goal_id,
                     phase_idx=state.current_phase_idx,
                     phase_name=phase["name"])

            await self._emit_progress(state, f"Starting phase: {phase['name']}")

            # Execute steps in this phase
            phase_success = await self._execute_phase_steps(state, phase, start_time)

            if phase_success:
                phase["status"] = "completed"
                log.info("phase_completed", goal_id=state.goal_id, phase_name=phase["name"])
            else:
                phase["status"] = "failed"
                log.warning("phase_failed", goal_id=state.goal_id, phase_name=phase["name"])
                # Don't stop the entire goal if one phase fails — mark and continue
                # unless it's a critical failure

            state.current_phase_idx += 1
            state.current_step_idx = 0
            state.save()

            # Adaptive re-planning check
            if state.total_steps_executed > 0 and state.total_steps_executed % REPLAN_INTERVAL == 0:
                await self._adaptive_replan(state)

        # All phases done
        state.status = "completed"
        state.elapsed_seconds = time.time() - start_time
        success_rate = (state.total_steps_succeeded / max(1, state.total_steps_executed)) * 100
        state.summary = (
            f"Goal completed. {state.total_steps_executed} steps executed across "
            f"{len(state.phases)} phases. Success rate: {success_rate:.0f}%."
        )

    async def _execute_phase_steps(self, state: GoalState, phase: dict, start_time: float) -> bool:
        """Execute all steps within a phase."""
        steps = phase.get("steps", [])
        all_succeeded = True

        while state.current_step_idx < len(steps):
            if self._is_cancelled(state.goal_id):
                return False

            step = steps[state.current_step_idx]
            if step["status"] in ("completed", "skipped"):
                state.current_step_idx += 1
                continue

            # Timeout check
            state.elapsed_seconds = time.time() - start_time
            if state.elapsed_seconds > state.timeout_seconds:
                return False

            # Max iterations check
            if state.total_steps_executed >= state.max_iterations:
                return False

            step["status"] = "running"
            state.total_steps_executed += 1

            log.info("step_executing",
                     goal_id=state.goal_id,
                     phase=phase["name"],
                     step_idx=state.current_step_idx,
                     action=step["action"][:80])

            success = await self._execute_single_step(state, step)

            if success:
                step["status"] = "completed"
                state.total_steps_succeeded += 1
            else:
                step["retries"] += 1
                if step["retries"] < MAX_STEP_RETRIES:
                    log.info("step_retrying", goal_id=state.goal_id, retry=step["retries"])
                    # Don't advance — retry this step
                    continue
                else:
                    # Try alternative approach
                    alternative_success = await self._try_alternative_approach(state, step, phase)
                    if alternative_success:
                        step["status"] = "completed"
                        state.total_steps_succeeded += 1
                    else:
                        step["status"] = "failed"
                        state.total_steps_failed += 1
                        all_succeeded = False

            state.current_step_idx += 1

            # Checkpoint every 5 steps
            if state.total_steps_executed % 5 == 0:
                state.save()

            await self._emit_progress(state, f"Step {state.current_step_idx}/{len(steps)}: {step['action'][:60]}")

        return all_succeeded

    async def _execute_single_step(self, state: GoalState, step: dict) -> bool:
        """Execute a single step using LLM to generate the exact command."""
        from backend.services.llm_service import llm_service

        # Build context from recent execution log
        recent = state.execution_log[-5:]
        context_str = ""
        if recent:
            context_str = "\n\nRecent execution history:\n"
            for entry in recent:
                icon = "✓" if entry.get("success") else "✗"
                context_str += f"  {icon} {entry.get('action', '')[:80]}\n"
                if entry.get("output"):
                    context_str += f"    Output: {entry['output'][:150]}\n"
                if entry.get("error"):
                    context_str += f"    Error: {entry['error'][:150]}\n"

        system_prompt = (
            "You are J.A.R.V.I.S. executing a specific step in a larger goal. "
            "Generate the exact command to execute this step.\n\n"
            "Output JSON only:\n"
            '{"command": "<run_os_command>the command</run_os_command>", "explanation": "brief explanation"}\n\n'
            "Available commands: desktop_*, browser_*, search_web|, fetch_url|, "
            "download_file|, PowerShell, create_excel|, generate_image|, agent_|type|action|payload\n\n"
            f"Overall goal: {state.goal}\n"
            f"Current phase: {state.current_phase_name}\n"
        )

        user_msg = (
            f"Execute this step: {step['action']}\n"
            f"{'Command hint: ' + step['command_hint'] if step.get('command_hint') else ''}"
            f"{context_str}"
        )

        try:
            response = await llm_service.get_response(
                user_message=user_msg,
                system_instructions=system_prompt,
                inject_memory=False,
            )

            parsed = _safe_json_parse(response)
            command = ""
            if parsed:
                command = parsed.get("command", "")
            else:
                # Try to extract command directly from response
                tag_match = re.search(r"<run_os_command>(.*?)</run_os_command>", response, re.DOTALL)
                if tag_match:
                    command = f"<run_os_command>{tag_match.group(1)}</run_os_command>"

            if not command:
                step["error"] = "LLM did not produce a command"
                state.execution_log.append({
                    "action": step["action"],
                    "success": False,
                    "error": "No command generated",
                    "timestamp": _now_iso(),
                })
                return False

            # Execute the command
            result = await self._dispatch_command(command)
            step["output"] = result.get("output", "")[:500]
            step["error"] = result.get("error", "")[:500]

            success = result.get("success", False)
            state.execution_log.append({
                "action": step["action"],
                "command": command[:200],
                "success": success,
                "output": step["output"],
                "error": step["error"],
                "timestamp": _now_iso(),
            })

            return success

        except Exception as e:
            step["error"] = str(e)
            state.execution_log.append({
                "action": step["action"],
                "success": False,
                "error": str(e),
                "timestamp": _now_iso(),
            })
            return False

    async def _try_alternative_approach(self, state: GoalState, step: dict, phase: dict) -> bool:
        """Ask LLM for an alternative approach when a step keeps failing."""
        from backend.services.llm_service import llm_service

        for attempt in range(MAX_ALTERNATIVE_APPROACHES):
            log.info("trying_alternative_approach",
                     goal_id=state.goal_id,
                     step=step["action"][:60],
                     attempt=attempt + 1)

            system_prompt = (
                "You are J.A.R.V.I.S. A step in your execution plan has failed multiple times. "
                "You must find an ALTERNATIVE approach to accomplish the same thing.\n\n"
                "Output JSON only:\n"
                '{"command": "<run_os_command>alternative command</run_os_command>", '
                '"approach": "brief description of the new approach"}\n\n'
                f"Original step: {step['action']}\n"
                f"Previous error: {step.get('error', 'Unknown')}\n"
                f"Attempt {attempt + 1}/{MAX_ALTERNATIVE_APPROACHES}\n"
                f"Overall goal: {state.goal}\n"
            )

            try:
                response = await llm_service.get_response(
                    user_message=f"Find an alternative way to: {step['action']}",
                    system_instructions=system_prompt,
                    inject_memory=False,
                )

                parsed = _safe_json_parse(response)
                if parsed and parsed.get("command"):
                    result = await self._dispatch_command(parsed["command"])
                    if result.get("success"):
                        step["output"] = result.get("output", "")[:500]
                        state.execution_log.append({
                            "action": f"[ALT] {step['action']}",
                            "command": parsed["command"][:200],
                            "success": True,
                            "output": step["output"],
                            "approach": parsed.get("approach", ""),
                            "timestamp": _now_iso(),
                        })
                        return True
            except Exception as e:
                log.debug("alternative_approach_failed", error=str(e))

        return False

    # ------------------------------------------------------------------
    # Adaptive Re-planning
    # ------------------------------------------------------------------

    async def _adaptive_replan(self, state: GoalState) -> None:
        """Re-evaluate the remaining plan based on execution results."""
        from backend.services.llm_service import llm_service

        remaining_phases = state.phases[state.current_phase_idx:]
        if not remaining_phases:
            return

        log.info("adaptive_replanning", goal_id=state.goal_id, step_count=state.total_steps_executed)

        # Build summary of what's been done
        completed_phases = [p["name"] for p in state.phases[:state.current_phase_idx] if p["status"] == "completed"]
        failed_phases = [p["name"] for p in state.phases[:state.current_phase_idx] if p["status"] == "failed"]
        recent_failures = [e for e in state.execution_log[-10:] if not e.get("success")]

        system_prompt = (
            "You are J.A.R.V.I.S. re-evaluating your execution plan midway through a complex goal. "
            "Based on what has succeeded and failed so far, decide if the remaining plan needs adjustment.\n\n"
            "Output JSON only:\n"
            '{"needs_replan": true/false, "reason": "why", '
            '"adjusted_phases": [{"name": "...", "steps": [{"action": "..."}]}]}\n\n'
            "If needs_replan is false, omit adjusted_phases.\n"
            "If true, provide the ADJUSTED remaining phases (not already completed ones).\n"
        )

        user_msg = (
            f"Goal: {state.goal}\n"
            f"Completed phases: {completed_phases}\n"
            f"Failed phases: {failed_phases}\n"
            f"Steps executed: {state.total_steps_executed}\n"
            f"Recent failures: {json.dumps(recent_failures[-3:], default=str)}\n"
            f"Remaining phases: {[p['name'] for p in remaining_phases]}\n"
        )

        try:
            response = await llm_service.get_response(
                user_message=user_msg,
                system_instructions=system_prompt,
                inject_memory=False,
            )

            parsed = _safe_json_parse(response)
            if parsed and parsed.get("needs_replan") and parsed.get("adjusted_phases"):
                new_phases = []
                for pi, pd in enumerate(parsed["adjusted_phases"][:20]):
                    phase = {
                        "name": pd.get("name", f"Adjusted Phase {pi + 1}"),
                        "description": pd.get("description", ""),
                        "steps": [],
                        "status": "pending",
                    }
                    for si, sd in enumerate(pd.get("steps", [])[:50]):
                        phase["steps"].append({
                            "action": sd.get("action", f"Step {si + 1}"),
                            "command_hint": sd.get("command_hint", ""),
                            "status": "pending",
                            "retries": 0,
                            "output": "",
                            "error": "",
                        })
                    new_phases.append(phase)

                if new_phases:
                    # Replace remaining phases
                    state.phases = state.phases[:state.current_phase_idx] + new_phases
                    log.info("goal_replanned",
                             goal_id=state.goal_id,
                             new_phase_count=len(new_phases),
                             reason=parsed.get("reason", "")[:100])
                    state.save()
        except Exception as e:
            log.debug("adaptive_replan_failed", error=str(e))

    # ------------------------------------------------------------------
    # Command Dispatch
    # ------------------------------------------------------------------

    async def _dispatch_command(self, command: str) -> Dict[str, Any]:
        """Execute a command through the system's command dispatch infrastructure."""
        if not command:
            return {"success": False, "error": "No command provided"}

        # Strip <run_os_command> tags
        cmd_clean = command.strip()
        tag_match = re.search(r"<run_os_command>(.*?)</run_os_command>", cmd_clean, re.DOTALL)
        if tag_match:
            cmd_clean = tag_match.group(1).strip()

        try:
            from backend.routers.router_chat import _dispatch_and_wait
            result = await _dispatch_and_wait(cmd_clean, f"Goal step: {cmd_clean[:80]}", timeout=60.0)
            return {
                "success": result.get("completed", False),
                "output": result.get("stdout", ""),
                "error": result.get("stderr", ""),
                "exit_code": result.get("exit_code", -1),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # WebSocket Progress
    # ------------------------------------------------------------------

    async def _emit_progress(self, state: GoalState, message: str) -> None:
        """Emit a progress event over WebSocket."""
        try:
            from backend.ws_manager import ws_manager

            await ws_manager.broadcast({
                "type": "goal_progress",
                "goal_id": state.goal_id,
                "goal": state.goal[:100],
                "status": state.status,
                "progress_percent": round(state.progress_percent, 1),
                "current_phase": state.current_phase_name,
                "total_steps_executed": state.total_steps_executed,
                "message": message,
            })
        except Exception:
            pass  # WebSocket broadcast is best-effort

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _is_cancelled(self, goal_id: str) -> bool:
        return goal_id in self._cancelled


# Singleton
goal_executor = GoalExecutor()
