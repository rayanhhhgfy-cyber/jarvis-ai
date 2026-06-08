from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

from shared.constants import AgentType, AgentStatus, TaskStatus
from shared.logger import get_logger
from shared.models import AgentInfo

log = get_logger("agent_tracker")


class AgentTracker:
    """
    Singleton service that tracks the real-time state of all 15 agent types.
    Listens to task lifecycle events and provides a queryable registry for the frontend.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentInfo] = {}
        self._event_bus = None

    def set_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus

    def initialize(self) -> None:
        """Create a record for every known agent type with IDLE status."""
        for agent_type in AgentType:
            agent_id = f"agent-{agent_type.value}"
            self._agents[agent_id] = AgentInfo(
                agent_id=agent_id,
                agent_type=agent_type,
                status=AgentStatus.IDLE,
                current_task_description=None,
            )
        log.info("agent_tracker_initialized", count=len(self._agents))

    def get_all_agents(self) -> List[AgentInfo]:
        return list(self._agents.values())

    def get_agent_by_type(self, agent_type: AgentType) -> Optional[AgentInfo]:
        agent_id = f"agent-{agent_type.value}"
        return self._agents.get(agent_id)

    def update_status(
        self,
        agent_type: AgentType,
        status: AgentStatus,
        task_description: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        agent_id = f"agent-{agent_type.value}"
        agent = self._agents.get(agent_id)
        if not agent:
            agent = AgentInfo(agent_id=agent_id, agent_type=agent_type, status=status)
            self._agents[agent_id] = agent

        old_status = agent.status
        agent.status = status
        agent.updated_at = datetime.utcnow()
        if task_description is not None:
            agent.current_task_description = task_description
        if error is not None:
            agent.error = error

        if status == AgentStatus.RUNNING:
            agent.task_count += 1

        log.debug(
            "agent_status_changed",
            agent_type=agent_type.value,
            old=old_status.value,
            new=status.value,
            task=task_description,
        )

    def mark_running(self, agent_type: AgentType, task_description: str) -> None:
        self.update_status(agent_type, AgentStatus.RUNNING, task_description=task_description)

    def mark_idle(self, agent_type: AgentType) -> None:
        self.update_status(agent_type, AgentStatus.IDLE)

    def mark_failed(self, agent_type: AgentType, error: str) -> None:
        self.update_status(agent_type, AgentStatus.FAILED, error=error)

    def get_summary(self) -> dict:
        """Return counts of agents per status."""
        summary = {"total": 0, "running": 0, "idle": 0, "failed": 0, "paused": 0, "other": 0}
        for agent in self._agents.values():
            summary["total"] += 1
            s = agent.status.value
            if s in summary:
                summary[s] += 1
            else:
                summary["other"] += 1
        return summary

    async def handle_task_event(self, event: dict) -> None:
        """Subscribe to event_bus TASK_STARTED/TASK_COMPLETED/TASK_FAILED to auto-update agents."""
        payload = event.get("payload", {}) or {}
        event_type = event.get("type", "")

        agent_type_str = payload.get("agent_type") or payload.get("type", "")
        try:
            agent_type = AgentType(agent_type_str)
        except (ValueError, KeyError):
            return

        if "started" in event_type or "created" in event_type:
            self.mark_running(agent_type, payload.get("title") or payload.get("description", ""))
        elif "completed" in event_type:
            self.mark_idle(agent_type)
        elif "failed" in event_type:
            self.mark_failed(agent_type, payload.get("error", "Unknown error"))


agent_tracker = AgentTracker()
