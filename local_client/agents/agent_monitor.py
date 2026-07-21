# ====================================================================
# JARVIS OMEGA — Monitor Agent
# ====================================================================
"""
Specialized Monitor Agent responsible for continuous host monitoring,
process checking, system metrics tracking, and resource leak detection.
"""

from __future__ import annotations

import os
import time
import psutil
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_monitor")

class AgentMonitor:
    """
    Monitoring and observation agent. Runs continuous background diagnostics
    on host CPU, memory leaks, runaway processes, and connection metrics.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_monitor"
        self.agent_type = AgentType.MONITOR

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Executes monitoring actions like full diagnostic vitals checks or process audits."""
        log.info("monitor_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "diagnostics")

            if action == "diagnostics" or action == "vitals":
                result_data = await self._run_diagnostics()
            elif action == "audit_process":
                result_data = await self._audit_process(task)
            else:
                raise ValueError(f"Unknown Monitor action: {action}")

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
            log.error("monitor_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _run_diagnostics(self) -> Dict[str, Any]:
        """Performs full resource utilization diagnostic report on host workstation."""
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        # Check system thermal sensor if available
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
            except Exception:
                pass

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_utilization": cpu,
            "memory": {
                "percent": mem.percent,
                "used_mb": mem.used / (1024 * 1024),
                "total_mb": mem.total / (1024 * 1024)
            },
            "disk": {
                "percent": disk.percent,
                "used_gb": disk.used / (1024 * 1024 * 1024),
                "total_gb": disk.total / (1024 * 1024 * 1024)
            },
            "temperatures": str(temps) if temps else "Not Available",
            "health": "healthy" if cpu < 90 else "degraded"
        }

    async def _audit_process(self, task: TaskDefinition) -> Dict[str, Any]:
        """Audits details of a specific process name or PID."""
        target_name = task.payload.get("process_name")
        target_pid = task.payload.get("pid")
        
        found_processes = []
        
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                pinfo = proc.info
                if target_pid and pinfo["pid"] == int(target_pid):
                    found_processes.append(pinfo)
                elif target_name and target_name.lower() in pinfo["name"].lower():
                    found_processes.append(pinfo)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "search_criteria": {"process_name": target_name, "pid": target_pid},
            "matching_processes_count": len(found_processes),
            "processes": found_processes[:10]  # Cap at 10 results
        }
