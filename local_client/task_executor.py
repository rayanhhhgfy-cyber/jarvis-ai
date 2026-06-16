# ====================================================================
# JARVIS OMEGA — Local Task Executor
# ====================================================================
"""
Routes and executes tasks dispatched from the backend. Dispatches them
to specific local agents (OS, Code, Document, etc.) and gathers results.
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

from shared.models import TaskDefinition, TaskResult
from shared.constants import TaskStatus, AgentType
from local_client.process_manager import local_process_manager
from shared.logger import get_logger

log = get_logger("task_executor")


class LocalTaskExecutor:
    """
    Core executor executing backend tasks. Integrates process manager
    and coordinates local agent workflows.
    """

    async def execute(self, task: TaskDefinition) -> TaskResult:
        """
        Executes a task based on agent type and parameters.
        Returns a structured TaskResult.
        """
        log.info("executing_task", task_id=task.task_id, type=task.agent_type.value)
        start_time = time.time()

        try:
            # Route based on AgentType
            if task.agent_type == AgentType.OS:
                result_data = await self._execute_os_command(task)
            elif task.agent_type == AgentType.CODE:
                result_data = await self._execute_code_task(task)
            else:
                # General routing fallback for other specialized agents
                result_data = await self._execute_generic_agent_task(task)

            elapsed = (time.time() - start_time) * 1000  # ms
            
            return TaskResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent_id or "local_executor",
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("task_execution_failed", task_id=task.task_id, error=err_msg)
            
            return TaskResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent_id or "local_executor",
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _execute_os_command(self, task: TaskDefinition) -> Dict[str, Any]:
        """Runs native system shell command payloads."""
        payload = task.payload
        cmd = payload.get("command")
        if not cmd:
            raise ValueError("No command provided in OS task payload")

        cwd = payload.get("cwd")
        env = payload.get("env")

        # Spawn via process manager
        proc_id = f"task_{task.task_id}"
        success, msg = await local_process_manager.spawn_process(proc_id, cmd, cwd=cwd, env=env)
        if not success:
            raise RuntimeError(f"Failed to spawn command process: {msg}")

        # Wait for finish
        code, stdout, stderr = await local_process_manager.wait_process(proc_id)

        # Always return structured result — even on non-zero exit codes
        # so the caller can display actual output to the user
        return {
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
        }

    async def _execute_code_task(self, task: TaskDefinition) -> Dict[str, Any]:
        """Placeholder code execution route. Will integrate AgentCode in Phase 5."""
        payload = task.payload
        file_path = payload.get("file_path")
        code_to_run = payload.get("code")

        if file_path and code_to_run:
            # Execute code directly
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tf:
                tf.write(code_to_run.encode())
                tf_path = tf.name

            try:
                proc_id = f"code_{task.task_id}"
                success, msg = await local_process_manager.spawn_process(proc_id, f"python {tf_path}")
                if not success:
                    raise RuntimeError(msg)
                code, stdout, stderr = await local_process_manager.wait_process(proc_id)
                return {"stdout": stdout, "stderr": stderr, "exit_code": code}
            finally:
                os.remove(tf_path)

        return {"status": "unsupported_code_format", "payload": payload}

    async def _execute_generic_agent_task(self, task: TaskDefinition) -> Dict[str, Any]:
        """Handles tasks routed to specialized agents (planning, browser, memory, research)."""
        import importlib

        try:
            # Try to dynamically load and run the agent from local_client.agents
            module_name = f"local_client.agents.agent_{task.agent_type.value}"
            class_name = f"Agent{task.agent_type.value.capitalize()}"

            module = importlib.import_module(module_name)
            agent_class = getattr(module, class_name)
            agent_instance = agent_class()

            result = await agent_instance.execute_task(task)

            if result.status == TaskStatus.FAILED:
                raise RuntimeError(result.error)
            return result.result or {}

        except (ImportError, AttributeError):
            # Fallback if specific agent file doesn't exist yet
            return {
                "agent_type": task.agent_type.value,
                "status": "not_implemented_yet",
                "message": f"Agent {task.agent_type.value} is not currently available on this node.",
                "timestamp": datetime.utcnow().isoformat(),
            }


# Global task executor instance
local_task_executor = LocalTaskExecutor()
