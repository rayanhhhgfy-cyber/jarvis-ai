# ====================================================================
# JARVIS OMEGA — System Health Monitor
# ====================================================================
"""
Tracks system resources (CPU, Memory, Disk, Network) and individual
module health status. Alerts the event bus on resource threshold breaches.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

import psutil

from shared.constants import HealthState, EventType
from shared.logger import get_logger
from shared.models import SystemVitals, ComponentHealth
from backend.config import settings

log = get_logger("health_monitor")


class HealthMonitor:
    """
    Monitors process and host resources using psutil.
    Manages module level health registration and queries.
    """

    def __init__(self) -> None:
        self._components: Dict[str, ComponentHealth] = {}
        self._event_bus = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = 15  # check every 15 seconds
        self._net_io_last = psutil.net_io_counters()
        self._net_time_last = time.time()

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    async def start(self) -> None:
        """Start the background monitoring task."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        log.info("health_monitor_started")

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("health_monitor_stopped")

    def register_component(self, name: str) -> None:
        """Register a subsystem for health status tracking."""
        self._components[name] = ComponentHealth(
            name=name,
            state=HealthState.HEALTHY,
            message="Component initialized",
            last_check=datetime.utcnow(),
        )

    def update_component_health(
        self,
        name: str,
        state: HealthState,
        message: str = "",
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update the health status of a registered component."""
        comp = self._components.get(name)
        if not comp:
            comp = ComponentHealth(name=name)
            self._components[name] = comp

        comp.state = state
        comp.message = message
        comp.latency_ms = latency_ms
        comp.last_check = datetime.utcnow()
        if metadata:
            comp.metadata = metadata

        if state == HealthState.CRITICAL:
            log.error("component_critical_health", name=name, message=message)
            if self._event_bus:
                asyncio.create_task(
                    self._event_bus.publish(
                        EventType.HEALTH_ALERT,
                        {"component": name, "state": state.value, "message": message},
                    )
                )

    def get_component_health(self) -> List[ComponentHealth]:
        """Retrieve health status list of all registered components."""
        return list(self._components.values())

    async def get_system_vitals(self) -> SystemVitals:
        """Collect host system resource metrics."""
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net_io = psutil.net_io_counters()

        # Calculate network speeds in MB/s
        now = time.time()
        time_diff = now - self._net_time_last
        self._net_time_last = now

        sent_speed = 0.0
        recv_speed = 0.0
        if time_diff > 0:
            sent_speed = ((net_io.bytes_sent - self._net_io_last.bytes_sent) / (1024 * 1024)) / time_diff
            recv_speed = ((net_io.bytes_recv - self._net_io_last.bytes_recv) / (1024 * 1024)) / time_diff

        self._net_io_last = net_io

        # CPU Temp (if supported by OS)
        cpu_temp = None
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if "coretemp" in temps:
                cpu_temp = temps["coretemp"][0].current
            elif "cpu_thermal" in temps:
                cpu_temp = temps["cpu_thermal"][0].current

        # Assess aggregate system health
        state = HealthState.HEALTHY
        if cpu > settings.max_cpu_percent or mem.percent > settings.max_memory_percent:
            state = HealthState.DEGRADED

        # Any critical components degrades system health
        for comp in self._components.values():
            if comp.state == HealthState.CRITICAL:
                state = HealthState.CRITICAL
                break
            elif comp.state == HealthState.DEGRADED and state == HealthState.HEALTHY:
                state = HealthState.DEGRADED

        from backend.task_manager import task_manager
        from backend.websocket_manager import ws_manager

        return SystemVitals(
            cpu_percent=cpu,
            memory_percent=mem.percent,
            memory_used_mb=mem.used / (1024 * 1024),
            memory_total_mb=mem.total / (1024 * 1024),
            disk_percent=disk.percent,
            disk_used_gb=disk.used / (1024 * 1024 * 1024),
            disk_total_gb=disk.total / (1024 * 1024 * 1024),
            network_sent_mb=sent_speed,
            network_recv_mb=recv_speed,
            cpu_temperature=cpu_temp,
            active_agents=ws_manager.connection_count,  # Proxy for active nodes/agents
            queued_tasks=task_manager.queue_size,
            health_state=state,
            timestamp=datetime.utcnow(),
        )

    async def _monitor_loop(self) -> None:
        """Background loop querying host resources and publishing alerts."""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                vitals = await self.get_system_vitals()

                # Trigger alert if resources exceed maximum limits
                if vitals.cpu_percent > settings.max_cpu_percent:
                    log.warning("cpu_threshold_exceeded", cpu=vitals.cpu_percent)
                    if self._event_bus:
                        await self._event_bus.publish(
                            EventType.HEALTH_ALERT,
                            {"resource": "cpu", "value": vitals.cpu_percent, "message": "High CPU utilization"},
                        )

                if vitals.memory_percent > settings.max_memory_percent:
                    log.warning("memory_threshold_exceeded", memory=vitals.memory_percent)
                    if self._event_bus:
                        await self._event_bus.publish(
                            EventType.HEALTH_ALERT,
                            {"resource": "memory", "value": vitals.memory_percent, "message": "High Memory utilization"},
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("health_monitor_loop_error", error=str(e))


# Global health monitor instance
health_monitor = HealthMonitor()
