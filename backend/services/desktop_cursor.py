from __future__ import annotations

import time
from typing import Optional

import pyautogui as pg

from shared.logger import get_logger

log = get_logger("desktop_cursor")


class CursorOverlay:
    """
    Moves the real system cursor so Sir sees exactly what JARVIS is doing.
    No Tkinter overlay — just pure pyautogui cursor movement like a human.
    """

    def __init__(self):
        self._running = True

    def start(self):
        self._running = True
        log.info("cursor_overlay_ready")

    def show(self, x: int, y: int, color: str = "", label: str = "", duration: float = 0.0):
        """Move the real system cursor to (x, y). No overlay window needed."""
        if not self._running:
            return
        try:
            pg.moveTo(x, y, duration=0.15)
        except Exception as e:
            log.debug("cursor_move_failed", error=str(e))

    def hide(self):
        pass

    def stop(self):
        self._running = False
        log.info("cursor_overlay_stopped")


cursor_overlay = CursorOverlay()
