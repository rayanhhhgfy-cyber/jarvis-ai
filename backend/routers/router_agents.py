from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from shared.models import AgentInfo
from shared.constants import AgentType, AgentStatus
from shared.logger import get_logger
from backend.services.agent_tracker import agent_tracker
from backend.task_manager import task_manager
from backend.websocket_manager import ws_manager

log = get_logger("router_agents")
router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.get("", response_model=List[AgentInfo])
async def list_all_agents():
    """Return status of every known agent type (running/idle/failed)."""
    agents = agent_tracker.get_all_agents()

    for agent in agents:
        queued = task_manager.get_tasks_by_agent(agent.agent_type)
        running_tasks = [t for t in queued if t.status.value == "running"]
        pending_tasks = [t for t in queued if t.status.value in ("queued", "assigned")]
        agent.task_count = len(running_tasks) + len(pending_tasks)
        if agent.task_count == 0 and agent.status == AgentStatus.RUNNING:
            agent.status = AgentStatus.IDLE

    return agents


@router.get("/summary")
async def get_agent_summary():
    """Return a summary of how many agents are in each state + running agent details."""
    agents = agent_tracker.get_all_agents()
    summary = {"total": len(agents), "running": [], "idle": [], "failed": [], "paused": [], "unknown": []}

    for agent in agents:
        s = agent.status.value
        entry = {
            "agent_id": agent.agent_id,
            "agent_type": agent.agent_type.value,
            "status": agent.status.value,
            "current_task": agent.current_task_description or "",
            "task_count": agent.task_count,
            "error": agent.error or "",
        }
        if s in summary:
            summary[s].append(entry)
        else:
            summary["unknown"].append(entry)

    queued_count = task_manager.queue_size
    total_tasks = task_manager.total_tasks
    return {
        "summary": {k: len(v) for k, v in summary.items() if isinstance(v, list)},
        "agents": agents,
        "queue_size": queued_count,
        "total_tasks": total_tasks,
    }


@router.get("/{agent_type}", response_model=AgentInfo)
async def get_agent_by_type(agent_type: AgentType):
    """Get detailed status of a specific agent type."""
    agent = agent_tracker.get_agent_by_type(agent_type)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent type '{agent_type.value}' not found")
    return agent


@router.post("/{agent_type}/reset")
async def reset_agent(agent_type: AgentType):
    """Reset an agent's status back to IDLE."""
    agent_tracker.mark_idle(agent_type)
    log.info("agent_reset", agent_type=agent_type.value)

    await ws_manager.broadcast({
        "type": "agent_update",
        "payload": {
            "agent_type": agent_type.value,
            "status": AgentStatus.IDLE.value,
            "current_task": None,
        },
    })

    return {"status": "reset", "agent_type": agent_type.value}
