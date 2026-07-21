# ====================================================================
# JARVIS OMEGA — Filesystem Watcher
# ====================================================================
"""
Watches local codebase folders for file changes (creation, modification,
deletion) using watchdog. Dispatches sync events to the backend command server.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from shared.logger import get_logger

log = get_logger("filesystem_watcher")


class WorkspaceChangeHandler(FileSystemEventHandler):
    """
    Listens to native filesystem events and executes callback dispatchers.
    """

    def __init__(self, callback: Any) -> None:
        super().__init__()
        self._callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:
        # Skip temporary, directories and dotfiles
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        if path.name.startswith(".") or "__pycache__" in path.parts:
            return

        # Invoke callback
        if self._callback:
            # Handle sync callback in event loop
            try:
                self._callback(event.event_type, str(path.as_posix()))
            except Exception as e:
                log.error("filesystem_callback_error", error=str(e))


class FilesystemWatcher:
    """
    Watches the workspace folder using native OS hooks.
    """

    def __init__(self, path_to_watch: str = "./workspace") -> None:
        self.path_to_watch = Path(path_to_watch)
        self._observer: Optional[Observer] = None
        self._callback = None

    def register_callback(self, callback: Any) -> None:
        """Register callback for event updates: callback(event_type, file_path)"""
        self._callback = callback

    async def start(self) -> None:
        """Start the observer watcher in background."""
        self.path_to_watch.mkdir(parents=True, exist_ok=True)
        log.info("starting_filesystem_watcher", watch_dir=str(self.path_to_watch))

        try:
            self._observer = Observer()
            handler = WorkspaceChangeHandler(self._dispatch_event)
            self._observer.schedule(handler, str(self.path_to_watch), recursive=True)
            self._observer.start()
        except Exception as e:
            log.error("filesystem_watcher_start_failed", error=str(e))

    def stop(self) -> None:
        """Stop the observer watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            log.info("filesystem_watcher_stopped")

    def _dispatch_event(self, event_type: str, filepath: str) -> None:
        """Helper to run callbacks or send websocket logs."""
        log.info("filesystem_changed", event=event_type, path=filepath)
        if self._callback:
            if asyncio.iscoroutinefunction(self._callback):
                asyncio.create_task(self._callback(event_type, filepath))
            else:
                self._callback(event_type, filepath)


# Global filesystem watcher instance
filesystem_watcher = FilesystemWatcher()
