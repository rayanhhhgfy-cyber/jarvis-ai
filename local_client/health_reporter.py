# ====================================================================
# JARVIS OMEGA — Local Health Reporter
# ====================================================================
"""
Reports host system resource utilization (CPU, RAM, disk, GPU) back to
the backend via the WebSocket client channel on an interval loop.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

import psutil

from shared.logger import get_logger

log = get_logger("health_reporter")


class HealthReporter:
    """
    Periodically samples host resource metrics and pushes them
    to the backend for the System Vitals dashboard panel.
    """

    def __init__(self, interval: int = 15) -> None:
        self._interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ws_client = None

    def set_websocket_client(self, ws_client: Any) -> None:
        self._ws_client = ws_client

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._report_loop())
        log.info("health_reporter_started", interval=self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("health_reporter_stopped")

    def collect_vitals(self) -> Dict[str, Any]:
        """Sample host metrics using psutil."""
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()

        vitals: Dict[str, Any] = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / (1024 * 1024), 1),
            "memory_total_mb": round(mem.total / (1024 * 1024), 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "net_bytes_sent": net.bytes_sent,
            "net_bytes_recv": net.bytes_recv,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # CPU temperature (best-effort)
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            for key in ("coretemp", "cpu_thermal", "k10temp"):
                if key in temps and temps[key]:
                    vitals["cpu_temperature"] = temps[key][0].current
                    break

        return vitals

    async def _report_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                vitals = self.collect_vitals()

                if self._ws_client:
                    await self._ws_client.send_message({
                        "type": "system_vitals",
                        "payload": vitals,
                    })
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("health_report_failed", error=str(e))


# Global health reporter instance
health_reporter = HealthReporter()
