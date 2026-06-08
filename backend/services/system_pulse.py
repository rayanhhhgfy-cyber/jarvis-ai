"""
System Pulse — psutil monitoring, gaming mode detection, predictive prefetching,
and cyber voice broadcast.

# pip install: psutil httpx
# pkg install: (none needed — psutil works on Termux via pip)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import psutil

from shared.logger import get_logger

log = get_logger("system_pulse")

_PULSE_INTERVAL = 5  # seconds between metric broadcasts
_CPU_ALERT_THRESHOLD = 90.0
_INTERACTION_LOG = Path.home() / ".jarvis" / "interaction_log.jsonl"


# =========================================================================
# SYSTEM MONITOR
# =========================================================================


class SystemMonitor:
    """
    Collects CPU, memory, disk metrics and broadcasts to WebSocket clients.
    Triggers voice alert when CPU > 90%.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._webhook: Optional[callable] = None
        self._last_cpu_alert = 0.0

    def set_webhook(self, callback: callable) -> None:
        """Set a callback for metric broadcasts. Receives dict."""
        self._webhook = callback

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._pulse_loop())
        log.info("system_pulse_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("system_pulse_stopped")

    async def _pulse_loop(self) -> None:
        while self._running:
            try:
                metrics = self.collect_metrics()
                if self._webhook:
                    await self._webhook(metrics)
                # CPU alert
                cpu = metrics.get("cpu_percent", 0)
                if cpu > _CPU_ALERT_THRESHOLD and (datetime.utcnow().timestamp() - self._last_cpu_alert) > 60:
                    self._last_cpu_alert = datetime.utcnow().timestamp()
                    try:
                        from backend.services.sound_engine import sound_engine, JarvisEvent, SoundPriority
                        await sound_engine.speak(
                            f"Warning. CPU at {cpu:.0f} percent.",
                            SoundPriority.WARNING,
                        )
                    except Exception:
                        pass
            except Exception as e:
                log.debug("pulse_iteration_error", error=str(e))
            await asyncio.sleep(_PULSE_INTERVAL)

    def collect_metrics(self) -> Dict[str, Any]:
        """Gather current system metrics."""
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            return {
                "cpu_percent": cpu,
                "memory_percent": mem.percent,
                "memory_available_mb": mem.available // (1024 * 1024),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free // (1024 ** 3),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            log.error("metrics_collection_failed", error=str(e))
            return {"error": str(e), "timestamp": datetime.utcnow().isoformat()}


# =========================================================================
# GAMING MODE DETECTOR
# =========================================================================


_GAMING_PROCESS_KEYWORDS = [
    "game", "unity", "unreal", "steam", "epic", "battlenet",
    "valorant", "league", "dota", "csgo", "minecraft",
]


class GamingModeDetector:
    """
    Detects if gaming-related processes are running.
    Sets a shared flag that background scrapers/workers can check.
    """

    def __init__(self):
        self.gaming_mode = False

    def check(self) -> bool:
        """Check running processes and update gaming_mode flag."""
        try:
            for proc in psutil.process_iter(["name"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    for kw in _GAMING_PROCESS_KEYWORDS:
                        if kw in name:
                            self.gaming_mode = True
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.gaming_mode = False
            return False
        except Exception:
            return self.gaming_mode


# =========================================================================
# PREDICTIVE PREFETCHER
# =========================================================================


class PredictivePrefetcher:
    """
    Parses interaction timestamps and identifies recurring daily work windows.
    Pre-warms vector memory context 15 minutes prior.
    """

    def __init__(self):
        self._scheduled = False

    async def analyze_patterns(self) -> Optional[str]:
        """
        Read interaction log and return the most common hour block.
        Returns ISO hour string like "09:00" or None.
        """
        if not _INTERACTION_LOG.exists():
            return None

        hour_counts: Dict[int, int] = {}
        try:
            for line in _INTERACTION_LOG.read_text().strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if ts:
                        dt = datetime.fromisoformat(ts)
                        hour_counts[dt.hour] = hour_counts.get(dt.hour, 0) + 1
                except (json.JSONDecodeError, ValueError):
                    continue

            if not hour_counts:
                return None

            peak_hour = max(hour_counts, key=hour_counts.get)
            return f"{peak_hour:02d}:00"
        except Exception as e:
            log.error("prefetch_analysis_failed", error=str(e))
            return None

    async def prefetch_window(self, window_hour: str = "09:00") -> None:
        """
        Pre-warm memory context. Called 15 minutes before the predicted window.
        """
        try:
            from backend.services.memory_service import memory_service
            context = await memory_service.get_context_for_query("daily briefing")
            log.info("memory_prefetched", context_length=len(str(context)))
        except Exception as e:
            log.debug("memory_prefetch_failed", error=str(e))


# =========================================================================
# CYBER VOICE BROADCAST
# =========================================================================


class CyberVoiceBroadcast:
    """
    Broadcasts critical exception payloads to all WebSocket clients
    with local voice alerts.
    """

    async def broadcast_critical(self, title: str, message: str, exception: Optional[Exception] = None) -> None:
        """Broadcast a critical event to UI clients + play voice alert."""
        try:
            from backend.websocket_manager import ws_manager
            payload = {
                "type": "critical_event",
                "payload": {
                    "title": title,
                    "message": message,
                    "error": str(exception) if exception else None,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }
            await ws_manager.broadcast(payload)
        except Exception as e:
            log.error("broadcast_failed", error=str(e))

        try:
            from backend.services.sound_engine import sound_engine, JarvisEvent
            await sound_engine.jarvis_alert(JarvisEvent.SERVER_DOWN)
        except Exception:
            pass


# Global instances
system_monitor = SystemMonitor()
gaming_detector = GamingModeDetector()
predictive_prefetcher = PredictivePrefetcher()
voice_broadcast = CyberVoiceBroadcast()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.system_pulse import system_monitor, gaming_detector
# await system_monitor.start()
# is_gaming = gaming_detector.check()
# print("Gaming mode:", is_gaming)
# await system_monitor.stop()
# ---
