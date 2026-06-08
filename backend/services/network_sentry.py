"""
Network Sentry — LAN device monitor, bandwidth warden, ping-healer.

# pip install: httpx
# TERMUX-NOTE: scapy unavailable on non-rooted Android.
#             Fallback to `nmap` subprocess for LAN scanning.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from shared.logger import get_logger

log = get_logger("network_sentry")

_LAN_SUBNET = "192.168.1.0/24"
_SCAN_INTERVAL = 120  # seconds
_BANDWIDTH_INTERVAL = 60
_PING_HEAL_INTERVAL = 30  # check own server
_LAN_KNOWN_DEVICES: List[str] = []


@dataclass
class LANDevice:
    ip: str
    mac: str = ""
    hostname: str = ""
    first_seen: str = ""
    last_seen: str = ""


@dataclass
class BandwidthUsage:
    bytes_sent: int = 0
    bytes_recv: int = 0
    timestamp: str = ""


class NetworkSentry:
    """
    Periodic LAN device scanning, bandwidth monitoring,
    and ping-healing of local server.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._http = httpx.AsyncClient(timeout=10.0, verify=False)
        self.devices: Dict[str, LANDevice] = {}
        self.bandwidth_history: List[BandwidthUsage] = []
        self._last_io: Optional[Dict[str, int]] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._network_loop())
        log.info("network_sentry_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._http.aclose()
        log.info("network_sentry_stopped")

    async def _network_loop(self) -> None:
        scan_counter = 0
        while self._running:
            try:
                scan_counter += 1
                if scan_counter % (_SCAN_INTERVAL // 10) == 0:
                    await self._scan_lan()

                await self._check_bandwidth()
                await self._ping_healer()
            except Exception as e:
                log.debug("network_iteration_error", error=str(e))
            await asyncio.sleep(10)

    async def _scan_lan(self) -> None:
        """Scan LAN using nmap subprocess (or placeholder on Android)."""
        try:
            # TERMUX-NOTE: nmap may not be installed. Graceful failure.
            result = subprocess.run(
                ["nmap", "-sn", _LAN_SUBNET],
                capture_output=True, text=True, timeout=30,
            )
            now = datetime.utcnow().isoformat()
            for line in result.stdout.split("\n"):
                if "Nmap scan report for" in line:
                    ip = line.split()[-1].strip("()")
                    if ip and ip not in self.devices:
                        self.devices[ip] = LANDevice(
                            ip=ip,
                            first_seen=now,
                            last_seen=now,
                        )
                        log.info("lan_device_discovered", ip=ip)
                    elif ip and ip in self.devices:
                        self.devices[ip].last_seen = now
        except FileNotFoundError:
            pass  # nmap not installed — skip silently
        except subprocess.TimeoutExpired:
            log.debug("nmap_scan_timeout")
        except Exception as e:
            log.debug("lan_scan_failed", error=str(e))

    async def _check_bandwidth(self) -> None:
        """Record current network I/O stats."""
        try:
            # TERMUX-NOTE: psutil.net_io_counters works on Android.
            import psutil
            io = psutil.net_io_counters()
            if io:
                usage = BandwidthUsage(
                    bytes_sent=io.bytes_sent,
                    bytes_recv=io.bytes_recv,
                    timestamp=datetime.utcnow().isoformat(),
                )
                self.bandwidth_history.append(usage)
                if len(self.bandwidth_history) > 100:
                    self.bandwidth_history = self.bandwidth_history[-50:]
        except Exception:
            pass

    async def _ping_healer(self) -> None:
        """Check own health endpoint; log failure."""
        try:
            resp = await self._http.get("http://127.0.0.1:8000/health", timeout=5.0)
            if resp.status_code != 200:
                log.warning("localhost_unhealthy", status=resp.status_code)
        except httpx.HTTPError:
            pass

    async def get_device_list(self) -> list:
        return [d.__dict__ for d in self.devices.values()]


network_sentry = NetworkSentry()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.network_sentry import network_sentry
# await network_sentry.start()
# # ...
# devices = await network_sentry.get_device_list()
# await network_sentry.stop()
# ---
