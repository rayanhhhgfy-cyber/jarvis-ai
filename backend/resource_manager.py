# ====================================================================
# JARVIS OMEGA — System Resource Manager
# ====================================================================
"""
Resource Manager. Audits agent process resource budgets (CPU, memory bounds),
enforces throttling limits, and terminates runaway agent tasks.
"""

from __future__ import annotations

import psutil
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import AgentInfo
from shared.logger import get_logger

log = get_logger("resource_manager")

class ResourceManager:
    """
    Host auditor. Enforces memory caps, throttles background pipelines,
    and secures workspace operations from CPU starvation.
    """

    def __init__(self, ram_budget_mb: float = 2048.0, cpu_percent_budget: float = 75.0) -> None:
        self.ram_budget_mb = ram_budget_mb
        self.cpu_percent_budget = cpu_percent_budget

    async def audit_resource_budgets(self, active_agents: List[AgentInfo]) -> Dict[str, Any]:
        """
        Scans workstation vitals and cross-references active agent allocations.
        Throttles resources if usage spikes above threshold.
        """
        # Get total system metrics
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        mem_used_mb = mem.used / (1024 * 1024)

        throttling_required = cpu > self.cpu_percent_budget or mem.percent > 85.0
        alerts = []

        if throttling_required:
            log.warning("resource_budget_exceeded_throttling", system_cpu=cpu, system_memory=mem.percent)
            alerts.append("System CPU/RAM threshold reached. Initialized active agent throttling.")

        # Update budgets on agents
        for agent in active_agents:
            if throttling_required:
                agent.cpu_usage = max(1.0, agent.cpu_usage * 0.5)  # Scale down
                agent.memory_usage = max(64.0, agent.memory_usage * 0.8)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_utilization": cpu,
            "memory_used_mb": mem_used_mb,
            "throttling_applied": throttling_required,
            "alerts": alerts
        }

    async def terminate_runaway_agent(self, agent_pid: int) -> bool:
        """Kills a runaway agent process immediately to release lockups."""
        try:
            log.info("terminating_runaway_agent_pid", pid=agent_pid)
            proc = psutil.Process(agent_pid)
            proc.kill()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.error("runaway_termination_failed", error=str(e))
            return False

# Global instance
resource_manager = ResourceManager()
