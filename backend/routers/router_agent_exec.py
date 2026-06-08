"""
Agent Execution Router — submit tasks directly to any sub-agent.
Provides REST endpoints for agent task submission and status tracking.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from backend.task_manager import task_manager
from local_client.agents import orchestrator as agent_orchestrator
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger
from shared.models import TaskDefinition

log = get_logger("router_agent_exec")

router = APIRouter(prefix="/api/agents/execute", tags=["Agent Execution"])


@router.post("/{agent_type}")
async def submit_agent_task(
    agent_type: str,
    task: TaskDefinition,
) -> Dict[str, Any]:
    """
    Submit a task to be executed by a specific agent type.
    The task will be queued and picked up by the background worker.
    """
    try:
        agent_enum = AgentType(agent_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    task.agent_type = agent_enum
    task_id = await task_manager.create_task(task)
    return {
        "task_id": task_id,
        "agent_type": agent_type,
        "status": TaskStatus.QUEUED.value,
    }


@router.post("/{agent_type}/run")
async def run_agent_task_direct(
    agent_type: str,
    task: TaskDefinition,
) -> Dict[str, Any]:
    """
    Execute a task on a specific agent immediately (blocking).
    Returns the TaskResult directly. Use for simple, fast operations.
    """
    try:
        agent_enum = AgentType(agent_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    task.agent_type = agent_enum
    task_id = await task_manager.create_task(task)

    from backend.services.agent_tracker import agent_tracker
    agent_tracker.mark_running(agent_enum, task.description or task.title)

    try:
        result = await agent_orchestrator.execute_task(task)
        if result.status == TaskStatus.COMPLETED:
            await task_manager.complete_task(result)
            agent_tracker.mark_idle(agent_enum)
        else:
            await task_manager.fail_task(task_id, result.error or "Agent execution failed", f"agent-{agent_type}")
            agent_tracker.mark_failed(agent_enum, result.error or "Task failed")
        return {
            "task_id": task_id,
            "status": result.status.value,
            "result": result.result,
            "error": result.error,
            "execution_time_ms": result.execution_time,
        }
    except Exception as e:
        agent_tracker.mark_failed(agent_enum, str(e))
        await task_manager.fail_task(task_id, str(e), f"agent-{agent_type}")
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")


@router.get("/{agent_type}/capabilities")
async def get_agent_capabilities(agent_type: str) -> Dict[str, Any]:
    """Return what actions an agent supports."""
    capabilities = {
        "research": {
            "actions": ["compile", "study"],
            "description": "Searches documentation, fetches API schemas, compiles research briefs",
            "payload_fields": {"topic": "string (required)"},
        },
        "code": {
            "actions": ["write", "read", "lint", "run"],
            "description": "Code generation, reading, linting, and execution",
            "payload_fields": {"file_path": "string", "content": "string", "code": "string"},
        },
        "browser": {
            "actions": ["navigate", "click", "type", "extract", "screenshot"],
            "description": "Browser automation via Playwright",
            "payload_fields": {"url": "string", "selector": "string", "text": "string"},
        },
        "os": {
            "actions": ["command", "file", "process"],
            "description": "Operating system commands and file operations",
            "payload_fields": {"command": "string", "path": "string"},
        },
        "planner": {
            "actions": ["decompose", "plan"],
            "description": "Breaks down goals into structured subtask sequences",
            "payload_fields": {"goal": "string (required)"},
        },
        "memory": {
            "actions": ["store", "search", "recall"],
            "description": "Long-term memory operations via SQLite",
            "payload_fields": {"content": "string", "query": "string"},
        },
        "vision": {
            "actions": ["analyze", "ocr", "describe"],
            "description": "Image analysis and OCR",
            "payload_fields": {"image_path": "string"},
        },
        "monitor": {
            "actions": ["health", "logs", "metrics"],
            "description": "System health monitoring and metrics collection",
            "payload_fields": {"target": "string"},
        },
        "testing": {
            "actions": ["run", "lint", "coverage"],
            "description": "Code testing, linting, and coverage analysis",
            "payload_fields": {"file_path": "string"},
        },
        "deployment": {
            "actions": ["deploy", "rollback", "status"],
            "description": "Application deployment management",
            "payload_fields": {"target": "string", "version": "string"},
        },
        "security": {
            "actions": ["scan", "audit", "check"],
            "description": "Security scanning and audit checks",
            "payload_fields": {"target": "string"},
        },
        "document": {
            "actions": ["generate", "convert", "summarize"],
            "description": "Document generation and processing",
            "payload_fields": {"format": "string", "content": "string"},
        },
        "video": {
            "actions": ["analyze", "transcribe", "generate"],
            "description": "Video analysis and generation",
            "payload_fields": {"source": "string"},
        },
        "repair": {
            "actions": ["diagnose", "fix", "recover"],
            "description": "System repair and recovery",
            "payload_fields": {"issue": "string"},
        },
    }
    info = capabilities.get(agent_type, {"actions": [], "description": "Unknown agent"})
    return {"agent_type": agent_type, **info}
