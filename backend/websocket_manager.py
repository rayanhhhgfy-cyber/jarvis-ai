# ====================================================================
# JARVIS OMEGA — WebSocket Manager
# ====================================================================
"""
WebSocket connection management: device registration, message routing,
broadcast, per-device channels, heartbeat, and security validation.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from shared.constants import EventType, WSMessageType
from shared.logger import get_logger
from shared.models import WSMessage
from shared.security import verify_device_token, verify_request_signature

log = get_logger("websocket_manager")


class ConnectedDevice:
    """Represents a single WebSocket-connected device."""

    def __init__(
        self,
        websocket: WebSocket,
        device_id: str,
        device_name: str = "",
        device_type: str = "unknown",
        session_token: str = "",
    ):
        self.websocket = websocket
        self.device_id = device_id
        self.device_name = device_name
        self.device_type = device_type
        self.session_token = session_token
        self.connected_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.latency_ms: float = 0.0
        self.subscriptions: Set[str] = set()
        self._ping_sent_at: Optional[float] = None

    @property
    def is_alive(self) -> bool:
        delta = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return delta < 90  # 3 missed heartbeats


class WebSocketManager:
    """
    Central WebSocket hub managing all device connections,
    message routing, broadcasting, and heartbeat monitoring.
    """

    def __init__(self) -> None:
        self._connections: Dict[str, ConnectedDevice] = {}
        self._event_bus = None  # Set during app startup
        self._heartbeat_interval = 30
        self._lock = asyncio.Lock()

    def set_event_bus(self, event_bus: Any) -> None:
        """Inject event bus reference."""
        self._event_bus = event_bus

    async def connect(
        self,
        websocket: WebSocket,
        device_id: str,
        device_name: str = "",
        device_type: str = "unknown",
        session_token: str = "",
    ) -> ConnectedDevice:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()

        device = ConnectedDevice(
            websocket=websocket,
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            session_token=session_token,
        )

        async with self._lock:
            # Close existing connection from same device
            if device_id in self._connections:
                old = self._connections[device_id]
                try:
                    await old.websocket.close(code=1000, reason="Replaced by new connection")
                except Exception:
                    pass

            self._connections[device_id] = device

        log.info(
            "device_connected",
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            total_connections=len(self._connections),
        )

        if self._event_bus:
            await self._event_bus.publish(
                EventType.DEVICE_CONNECTED,
                {"device_id": device_id, "device_name": device_name},
            )

        return device

    async def disconnect(self, device_id: str) -> None:
        """Remove a device connection."""
        async with self._lock:
            device = self._connections.pop(device_id, None)

        if device:
            log.info("device_disconnected", device_id=device_id)
            if self._event_bus:
                await self._event_bus.publish(
                    EventType.DEVICE_DISCONNECTED,
                    {"device_id": device_id},
                )

    async def send_to_device(
        self,
        device_id: str,
        message: Dict[str, Any] | WSMessage,
    ) -> bool:
        """Send a message to a specific device."""
        device = self._connections.get(device_id)
        if not device:
            log.warning("send_failed_no_device", device_id=device_id)
            return False

        try:
            data = message.model_dump(mode="json") if isinstance(message, WSMessage) else message
            await device.websocket.send_json(data)
            return True
        except Exception as e:
            log.error("send_failed", device_id=device_id, error=str(e))
            await self.disconnect(device_id)
            return False

    async def broadcast(
        self,
        message: Dict[str, Any] | WSMessage,
        exclude: Optional[Set[str]] = None,
    ) -> int:
        """Broadcast a message to all connected devices."""
        exclude = exclude or set()
        data = message.model_dump(mode="json") if isinstance(message, WSMessage) else message
        sent = 0
        disconnected = []

        for device_id, device in list(self._connections.items()):
            if device_id in exclude:
                continue
            try:
                await device.websocket.send_json(data)
                sent += 1
            except Exception:
                disconnected.append(device_id)

        for device_id in disconnected:
            await self.disconnect(device_id)

        return sent

    async def send_terminal_log(
        self,
        message: str,
        level: str = "info",
        source: str = "system",
        exclude: Optional[Set[str]] = None,
    ) -> None:
        """Broadcast a terminal log entry to all connected dashboards."""
        log_entry = {
            "type": WSMessageType.TERMINAL_LOG.value,
            "payload": {
                "message": message,
                "level": level,
                "source": source,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
        await self.broadcast(log_entry, exclude=exclude)

    async def handle_heartbeat(self, device_id: str) -> None:
        """Process a heartbeat from a device."""
        device = self._connections.get(device_id)
        if device:
            now = datetime.utcnow()
            if device._ping_sent_at:
                device.latency_ms = (time.time() - device._ping_sent_at) * 1000
                device._ping_sent_at = None
            device.last_heartbeat = now

    async def send_heartbeat_pings(self) -> None:
        """Send heartbeat pings to all connected devices."""
        disconnected = []
        for device_id, device in list(self._connections.items()):
            if not device.is_alive:
                disconnected.append(device_id)
                continue
            try:
                device._ping_sent_at = time.time()
                await device.websocket.send_json({
                    "type": WSMessageType.HEARTBEAT.value,
                    "payload": {"server_time": datetime.utcnow().isoformat()},
                })
            except Exception:
                disconnected.append(device_id)

        for device_id in disconnected:
            await self.disconnect(device_id)

    def get_connected_devices(self) -> List[Dict[str, Any]]:
        """Get list of all connected devices."""
        return [
            {
                "device_id": d.device_id,
                "device_name": d.device_name,
                "device_type": d.device_type,
                "connected_at": d.connected_at.isoformat(),
                "last_heartbeat": d.last_heartbeat.isoformat(),
                "latency_ms": d.latency_ms,
                "is_alive": d.is_alive,
            }
            for d in self._connections.values()
        ]

    def get_device(self, device_id: str) -> Optional[ConnectedDevice]:
        """Get a connected device by ID."""
        return self._connections.get(device_id)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Global WebSocket manager instance
ws_manager = WebSocketManager()
