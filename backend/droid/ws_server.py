# ====================================================================
# JARVIS OMEGA — Droid WebSocket Server Router
# ====================================================================
"""
Dedicated routing hub for cross-device ("droid") messages.

Devices send envelopes over the main /ws/{device_id} connection. This module:
- parses incoming envelope messages
- routes COMMAND_RESULT to pending futures via device_manager
- routes NOTIFICATION to device_manager (hook)
"""

from __future__ import annotations

import json
from typing import Any, Dict

from shared.logger import get_logger
from backend.droid.device_manager import droid_device_manager

from shared.constants import WSMessageType

log = get_logger("droid.ws_server")


async def handle_droid_envelope(*, device_id: str, message: Dict[str, Any]) -> None:
    """
    Handle an already-parsed JSON message as an envelope.
    """
    if not isinstance(message, dict):
        return

    envelope_type = message.get("type")
    correlation_id = message.get("correlation_id")
    payload = message.get("payload") or {}

    if envelope_type == "RESULT":
        # Expected shape:
        # { type:"RESULT", correlation_id, device_id, payload:{ok,data,error,id?} }
        result_payload = {
            "id": correlation_id,
            "ok": payload.get("ok", False),
            "data": payload.get("data"),
            "error": payload.get("error"),
        }
        await droid_device_manager.handle_result(correlation_id=correlation_id, result=result_payload)
        return

    if envelope_type == "NOTIFICATION":
        await droid_device_manager.handle_notification(notification=payload)
        return

    # Heartbeats/unknown types are handled elsewhere
    log.debug("droid_unhandled_envelope_type", device_id=device_id, envelope_type=envelope_type)
