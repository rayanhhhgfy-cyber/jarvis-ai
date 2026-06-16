# ====================================================================
# JARVIS OMEGA — UI Manager
# ====================================================================
"""
Manages frontend UI WebSocket connections and broadcasts.
"""

from __future__ import annotations
from fastapi import WebSocket

class UIManager:
    def __init__(self):
        self._ui_clients: set[WebSocket] = set()

    def add_client(self, websocket: WebSocket):
        self._ui_clients.add(websocket)

    def remove_client(self, websocket: WebSocket):
        self._ui_clients.discard(websocket)

    async def broadcast(self, message: dict):
        """Push a message to ALL connected frontend dashboard clients."""
        dead = []
        for ws in self._ui_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ui_clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._ui_clients)

ui_manager = UIManager()
