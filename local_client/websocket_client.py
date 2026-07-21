# ====================================================================
# JARVIS OMEGA — Local WebSocket Client
# ====================================================================
"""
Persistent WebSocket client connecting the local daemon to the backend API.
Handles auto-reconnections, heartbeats, task receiving, and result uploading.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime
from typing import Optional, Any, Dict

import websockets

from shared.constants import WSMessageType, TaskStatus
from shared.logger import get_logger
from shared.models import WSMessage, TaskDefinition, TaskResult
from backend.config import settings
from local_client.state_manager import local_state_manager
from local_client.task_executor import local_task_executor

log = get_logger("websocket_client")


class LocalWebSocketClient:
    """
    Maintains persistent WS connection to Command Center Backend.
    Parses messages and triggers local execution.
    """

    def __init__(self) -> None:
        self._connection: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Honor the central setting rather than a magic constant.
        self._reconnect_delay = settings.ws_reconnect_delay

    async def start(self) -> None:
        """Start the background connection loop."""
        self._running = True
        self._task = asyncio.create_task(self._connect_loop())
        log.info("websocket_client_started")

    async def stop(self) -> None:
        """Close connection and stop client loop."""
        self._running = False
        if self._connection:
            await self._connection.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("websocket_client_stopped")

    async def send_message(self, message: WSMessage | Dict[str, Any]) -> bool:
        """Send a message to the backend."""
        if not self._connection:
            log.warning("cannot_send_ws_not_connected")
            return False

        try:
            data = message.model_dump(mode="json") if isinstance(message, WSMessage) else message
            await self._connection.send(json.dumps(data))
            return True
        except Exception as e:
            log.error("ws_send_failed", error=str(e))
            return False

    async def _connect_loop(self) -> None:
        """Connection maintenance loop."""
        while self._running:
            device_id = local_state_manager.device_id
            token = local_state_manager.access_token
            ws_url = f"{local_state_manager.ws_url}/{device_id}?token={token}"

            log.info("ws_connecting_to_backend", url=local_state_manager.ws_url)
            try:
                async with websockets.connect(ws_url) as ws:
                    self._connection = ws
                    log.info("ws_connected_successfully")

                    # Process incoming messages
                    async for raw_msg in ws:
                        await self._handle_raw_message(raw_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("ws_connection_error", error=str(e))
                self._connection = None

            # Reconnection delay
            log.info("ws_reconnecting_in_seconds", seconds=self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)

    async def _handle_raw_message(self, raw_msg: str) -> None:
        """Parse and route messages received from backend."""
        try:
            data = json.loads(raw_msg)
            msg_type = data.get("type")
            payload = data.get("payload", {})

            log.debug("ws_message_received", type=msg_type)

            # 1. Heartbeat check
            if msg_type == WSMessageType.HEARTBEAT.value:
                # Respond to heartbeat ping
                await self.send_message({
                    "type": WSMessageType.HEARTBEAT.value,
                    "payload": {"status": "alive"},
                })

            # 2. Task execution dispatches
            elif msg_type == "execute_task":
                task_def = TaskDefinition(**payload)
                asyncio.create_task(self._process_and_reply_task(task_def))

            # 3. Handle approvals/commands
            elif msg_type == "approval_response":
                log.info("received_approval_response", payload=payload)

        except Exception as e:
            log.error("ws_message_handler_error", error=str(e), trace=traceback.format_exc())

    async def _process_and_reply_task(self, task: TaskDefinition) -> None:
        """Executes a task locally and returns results back to backend."""
        # Report start
        await self.send_message({
            "type": "task_update",
            "payload": {
                "task_id": task.task_id,
                "status": TaskStatus.RUNNING.value,
                "started_at": datetime.utcnow().isoformat(),
            }
        })

        # Execute
        result = await local_task_executor.execute(task)

        # Upload results
        await self.send_message({
            "type": "task_result",
            "payload": result.model_dump(mode="json"),
        })


# Global WebSocket client instance
websocket_client = LocalWebSocketClient()
