# ====================================================================
# JARVIS OMEGA — Droid Command Router
# ====================================================================
"""
Routes structural cross-device commands produced by the LLM/command interpreter
into actual connected device execution.

This router is intentionally thin:
- it dispatches COMMAND envelopes via DroidDeviceManager
- it returns the raw result back to the chat router
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from shared.logger import get_logger
from backend.droid.device_manager import droid_device_manager

log = get_logger("droid.router")


class DroidRouter:
    """
    High-level routing entrypoint for droid commands.
    """

    async def execute(
        self,
        *,
        user_id: Optional[str],
        target_device_id: str,
        cmd: str,
        payload: Dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        if not target_device_id or not isinstance(target_device_id, str):
            raise ValueError("target_device_id is required")
        if not cmd or not isinstance(cmd, str):
            raise ValueError("cmd is required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        # Dispatch via device manager and return raw result payload
        raw_result = await droid_device_manager.send_command_and_wait(
            user_id=user_id,
            target_device_id=target_device_id,
            cmd=cmd,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return raw_result


# Global singleton
droid_router = DroidRouter()
