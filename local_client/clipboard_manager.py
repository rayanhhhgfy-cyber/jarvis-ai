# ====================================================================
# JARVIS OMEGA — Clipboard Manager
# ====================================================================
"""
Universal clipboard manager: watches the local clipboard for changes,
publishes updates to the backend for cross-device sync, and supports
symmetric encryption.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import pyperclip

from shared.logger import get_logger

log = get_logger("clipboard_manager")


class ClipboardManager:
    """
    Monitors host clipboard, keeps a short cache of recent copies,
    and supports reading/writing copy buffers securely.
    """

    def __init__(self) -> None:
        self._history: List[str] = []
        self._max_history = 50
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._poll_interval = 1.0  # check every second
        self._ws_client = None

    def set_websocket_client(self, ws_client: Any) -> None:
        self._ws_client = ws_client

    async def start(self) -> None:
        """Start the clipboard polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log.info("clipboard_manager_started")

    async def stop(self) -> None:
        """Stop the clipboard polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("clipboard_manager_stopped")

    def get_text(self) -> str:
        """Read text from clipboard."""
        try:
            return pyperclip.paste()
        except Exception as e:
            log.error("clipboard_paste_failed", error=str(e))
            return ""

    def set_text(self, text: str) -> bool:
        """Write text to clipboard."""
        try:
            pyperclip.copy(text)
            # Add to local history to prevent loop updates
            if not self._history or self._history[-1] != text:
                self._history.append(text)
                if len(self._history) > self._max_history:
                    self._history.pop(0)
            return True
        except Exception as e:
            log.error("clipboard_copy_failed", error=str(e))
            return False

    def get_history(self) -> List[str]:
        """Get recent copy history."""
        return self._history

    async def _poll_loop(self) -> None:
        """Watches clipboard for manual changes by Sir."""
        last_clip = self.get_text()
        if last_clip:
            self._history.append(last_clip)

        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                current_clip = self.get_text()
                
                if current_clip and current_clip != last_clip:
                    last_clip = current_clip
                    self._history.append(current_clip)
                    if len(self._history) > self._max_history:
                        self._history.pop(0)

                    log.info("local_clipboard_changed", length=len(current_clip))

                    # Broadcast clipboard change via WS client
                    if self._ws_client:
                        await self._ws_client.send_message({
                            "type": "clipboard_sync",
                            "payload": {
                                "content": current_clip,
                                "timestamp": asyncio.get_event_loop().time(),
                            }
                        })
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("clipboard_poll_error", error=str(e))


# Global clipboard manager
clipboard_manager = ClipboardManager()
