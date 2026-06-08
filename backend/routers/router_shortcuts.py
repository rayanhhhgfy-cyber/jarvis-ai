# ====================================================================
# JARVIS OMEGA — Shortcuts Router
# ====================================================================
"""
Short action macros and workflow triggers. Allows Sir to execute common
pre-programmed scripts and tasks with single clicks.
"""

from __future__ import annotations

from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, status

from shared.models import TaskDefinition
from shared.constants import AgentType, TaskPriority
from backend.task_manager import task_manager
from shared.logger import get_logger

log = get_logger("router_shortcuts")
router = APIRouter(prefix="/api/shortcuts", tags=["Shortcuts"])

# Configured quick actions list
SHORTCUTS = [
    {
        "id": "scan_workspace",
        "title": "Scan Workspace",
        "description": "Performs recursive AST analysis on project files.",
        "agent_type": AgentType.OS.value,
        "payload": {"command": "scan_project"},
    },
    {
        "id": "health_check",
        "title": "System Diagnostic",
        "description": "Performs aggregate module diagnostic checks.",
        "agent_type": AgentType.MONITOR.value,
        "payload": {"command": "run_diagnostics"},
    },
    {
        "id": "clean_logs",
        "title": "Purge Logs",
        "description": "Deletes old files inside logs directory.",
        "agent_type": AgentType.OS.value,
        "payload": {"command": "clean_logs"},
    },
]


@router.get("")
async def get_shortcuts() -> List[Dict[str, Any]]:
    """Retrieve list of quick actions and triggers."""
    return SHORTCUTS


@router.post("/{shortcut_id}/execute")
async def execute_shortcut(shortcut_id: str):
    """Triggers the execution of a pre-configured shortcut macro."""
    shortcut = next((s for s in SHORTCUTS if s["id"] == shortcut_id), None)
    if not shortcut:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shortcut macro not found",
        )

    # Spawn task via Task Manager
    task = TaskDefinition(
        title=shortcut["title"],
        description=shortcut["description"],
        agent_type=AgentType(shortcut["agent_type"]),
        priority=TaskPriority.HIGH,
        payload=shortcut["payload"],
    )

    task_id = await task_manager.create_task(task)
    log.info("shortcut_task_created", shortcut_id=shortcut_id, task_id=task_id)
    return {"status": "triggered", "task_id": task_id}
