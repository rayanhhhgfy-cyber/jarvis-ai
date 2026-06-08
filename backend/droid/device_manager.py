# ====================================================================
# JARVIS OMEGA — Droid Device Manager
# ====================================================================
"""
Correlates cross-device commands/results and abstracts the routing layer.

This manager:
- tracks pending command Futures by correlation id
- sends command envelopes to the appropriate connected device via WebSocket
- awaits results with timeout
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from shared.logger import get_logger
from backend.websocket_manager import ws_manager

log = get_logger("droid.device_manager")


@dataclass(frozen=True)
class DeviceSendResult:
    delivered: bool
    device_id: str
    error: Optional[str] = None


class DroidDeviceManager:
    def __init__(self) -> None:
        self._pending: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def _new_correlation_id(self) -> str:
        return uuid.uuid4().hex

    async def send_command_and_wait(
        self,
        *,
        user_id: Optional[str],
        target_device_id: str,
        cmd: str,
        payload: Dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Send a command to a connected device and await its result.

        Returns the raw result payload from the device:
          { "id": correlation_id, "ok": bool, "data": {...}|None, "error": str|None }
        """
        if not target_device_id or not isinstance(target_device_id, str):
            raise ValueError("target_device_id is required")
        if not cmd or not isinstance(cmd, str):
            raise ValueError("cmd is required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        correlation_id = self._new_correlation_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        async with self._lock:
            self._pending[correlation_id] = fut

        envelope = {
            "type": "COMMAND",
            "device_id": target_device_id,
            "user_id": user_id,
            "correlation_id": correlation_id,
            "payload": {
                "cmd": cmd,
                **payload,
            },
        }

        send_res = await self._send_envelope(target_device_id, envelope)
        if not send_res.delivered:
            async with self._lock:
                self._pending.pop(correlation_id, None)
            raise RuntimeError(send_res.error or "Failed to deliver command")

        try:
            raw_result = await asyncio.wait_for(fut, timeout=timeout_seconds)
            return raw_result
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(correlation_id, None)
            raise TimeoutError(f"Timed out waiting for result correlation_id={correlation_id}")
        finally:
            async with self._lock:
                f = self._pending.get(correlation_id)
                if f is not None and f.done() is False:
                    f.cancel()

    async def _send_envelope(self, device_id: str, envelope: Dict[str, Any]) -> DeviceSendResult:
        device = ws_manager.get_device(device_id)
        if not device:
            return DeviceSendResult(delivered=False, device_id=device_id, error="Device not connected")
        try:
            await device.websocket.send_json(envelope)
            return DeviceSendResult(delivered=True, device_id=device_id)
        except Exception as e:
            return DeviceSendResult(delivered=False, device_id=device_id, error=str(e))

    async def handle_result(self, *, correlation_id: str, result: Dict[str, Any]) -> None:
        """
        Called by ws router when a device returns a result for a correlation id.
        """
        if not correlation_id:
            return

        async with self._lock:
            fut = self._pending.get(correlation_id)

        if not fut:
            log.warning("droid_result_unknown_correlation", correlation_id=correlation_id)
            return

        if fut.done():
            return

        fut.set_result(result)

    async def handle_notification(self, *, notification: Dict[str, Any]) -> None:
        """
        Placeholder hook: notifications are pushed via backend routers/services in future.
        For now, we log them; router layer can extend.
        """
        try:
            log.info("droid_notification_received", notification=notification)
        except Exception:
            pass


# Global singleton
droid_device_manager = DroidDeviceManager()
