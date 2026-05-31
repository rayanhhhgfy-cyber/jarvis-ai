# ====================================================================
# JARVIS OMEGA — Agent Registry & Control Router
# ====================================================================
"""
REST endpoints to list active agents, monitor resource consumption,
spawn agent child processes, and terminate runaway nodes.
"""

from __future__ import annotations

from typing import List, Dict

from fastapi import APIRouter, HTTPException, status

from shared.models import AgentInfo
from shared.constants import AgentType, AgentStatus
from shared.logger import get_logger

log = get_logger("router_agents")
router = APIRouter(prefix="/api/agents", tags=["Agents"])

# Global in-memory registry of agent process structures
active_agents: Dict[str, AgentInfo] = {}


@router.get("", response_model=List[AgentInfo])
async def list_active_agents():
    """Retrieve runtime status of all currently spawned agent nodes."""
    return list(active_agents.values())


@router.post("/spawn", response_model=AgentInfo)
async def spawn_agent(agent_type: AgentType, parent_id: str = None):
    """Spawns a new autonomous agent process of the specified category."""
    log.info("request_spawn_agent", type=agent_type.value, parent=parent_id)

    # Instantiate AgentInfo schema
    info = AgentInfo(
        agent_type=agent_type,
        parent_id=parent_id,
        status=AgentStatus.IDLE,
    )
    active_agents[info.agent_id] = info
    return info


@router.get("/{agent_id}", response_model=AgentInfo)
async def inspect_agent(agent_id: str):
    """Retrieve detailed runtime logs and vitals for a specific agent."""
    agent = active_agents.get(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent node not found",
        )
    return agent


@router.post("/{agent_id}/terminate")
async def terminate_agent(agent_id: str):
    """Gracefully terminates or kills a running agent process."""
    log.info("request_terminate_agent", agent_id=agent_id)
    agent = active_agents.pop(agent_id, None)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent node not found or already terminated",
        )
    return {"status": "terminated", "agent_id": agent_id}
