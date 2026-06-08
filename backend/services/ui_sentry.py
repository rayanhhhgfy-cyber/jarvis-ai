"""
UI Sentry — watchdog file observer for frontend changes, Tailwind lint, WebSocket push.

# pip install: watchdog
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from shared.logger import get_logger

log = get_logger("ui_sentry")

_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
_DEBOUNCE_SECONDS = 2.0


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_modified(self, event):
        if event.src_path.endswith((".tsx", ".ts", ".css", ".js")):
            self.callback(event.src_path)


class UISentry:
    """
    Monitors frontend source files for changes and triggers
    Tailwind lint + WebSocket notification.
    """

    def __init__(self):
        self._observer: Optional[Observer] = None
        self._change_queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        if not _FRONTEND_DIR.exists():
            log.info("ui_sentry_frontend_dir_missing", path=str(_FRONTEND_DIR))
            return

        # File system watcher
        self._observer = Observer()
        handler = _ChangeHandler(self._on_file_change)
        self._observer.schedule(handler, str(_FRONTEND_DIR / "app"), recursive=True)
        self._observer.schedule(handler, str(_FRONTEND_DIR / "components"), recursive=True)
        self._observer.start()

        # Debounced processor
        self._task = asyncio.create_task(self._debounce_loop())
        log.info("ui_sentry_started", frontend_dir=str(_FRONTEND_DIR))

    def _on_file_change(self, path: str):
        self._change_queue.put_nowait(path)

    async def _debounce_loop(self):
        while self._running:
            try:
                path = await self._change_queue.get()
                # Debounce: wait for quiet period
                await asyncio.sleep(_DEBOUNCE_SECONDS)
                # Drain queue
                while not self._change_queue.empty():
                    try:
                        self._change_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                await self._run_lint()
                await self._notify_ws(path)
            except Exception as e:
                log.debug("ui_sentry_error", error=str(e))

    async def _run_lint(self):
        """Run Tailwind CSS lint via subprocess."""
        try:
            result = subprocess.run(
                ["npx", "tailwindcss", "--lint"],
                cwd=str(_FRONTEND_DIR),
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                log.warning("tailwind_lint_issues", stderr=result.stderr[:200])
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            log.debug("tailwind_lint_timeout")
        except Exception as e:
            log.debug("tailwind_lint_error", error=str(e))

    async def _notify_ws(self, path: str):
        """Push change notification to WebSocket clients."""
        try:
            from backend.websocket_manager import ws_manager
            await ws_manager.broadcast({
                "type": "ui_change",
                "payload": {"file": path, "timestamp": __import__("datetime").datetime.utcnow().isoformat()},
            })
        except Exception:
            pass

    async def stop(self):
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("ui_sentry_stopped")


ui_sentry = UISentry()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.ui_sentry import ui_sentry
# await ui_sentry.start()
# ...
# await ui_sentry.stop()
# ---
