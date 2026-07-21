# ====================================================================
# JARVIS OMEGA — Local Client Daemon
# ====================================================================
"""
Main daemon entry point for Sir's workstation. Orchestrates all local
subsystems: WebSocket client, clipboard monitor, filesystem watcher,
microphone listener, wake-word detector, health reporter, and agents.
Runs forever until terminated.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Optional

from shared.logger import setup_logging, get_logger

setup_logging(log_dir="./logs", log_level="INFO", log_format="console")
log = get_logger("daemon")

from local_client.state_manager import local_state_manager
from local_client.websocket_client import websocket_client
from local_client.clipboard_manager import clipboard_manager
from local_client.microphone_listener import microphone_listener
from local_client.wakeword_detector import wakeword_detector
from local_client.screenshot_manager import screenshot_manager
from local_client.filesystem_watcher import filesystem_watcher
from local_client.workspace_scanner import workspace_scanner
from local_client.health_reporter import health_reporter


class JarvisDaemon:
    """
    The always-on local daemon process. Orchestrates all client-side
    services and maintains a persistent backend connection.
    """

    def __init__(self) -> None:
        self._running = False

    async def start(self) -> None:
        """Boot all subsystems and enter the forever-loop."""
        self._running = True
        log.info("============================================")
        log.info("    JARVIS OMEGA — Local Daemon Starting     ")
        log.info("============================================")
        log.info("device_id", device_id=local_state_manager.device_id)
        log.info("device_name", device_name=local_state_manager.device_name)

        # ---- Wire cross-references ----
        clipboard_manager.set_websocket_client(websocket_client)
        health_reporter.set_websocket_client(websocket_client)

        # ---- Start subsystems in dependency order ----
        # 1. WebSocket connection to backend
        await websocket_client.start()

        # 2. Health reporter (pushes vitals to backend)
        await health_reporter.start()

        # 3. Clipboard sync
        await clipboard_manager.start()

        # 4. Filesystem watcher
        await filesystem_watcher.start()

        # 5. Microphone + wake word
        await microphone_listener.start()
        await wakeword_detector.start()

        log.info("============================================")
        log.info("    JARVIS OMEGA — All Systems Online        ")
        log.info("============================================")

        # ---- Forever loop ----
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Graceful shutdown of all subsystems."""
        log.info("jarvis_daemon_shutting_down")
        self._running = False

        await wakeword_detector.stop()
        await microphone_listener.stop()
        filesystem_watcher.stop()
        await clipboard_manager.stop()
        await health_reporter.stop()
        await websocket_client.stop()

        log.info("jarvis_daemon_shutdown_complete")


# ---- Entry Point ----

daemon = JarvisDaemon()


def _handle_signal(sig, frame):
    log.info("received_signal", signal=sig)
    asyncio.get_event_loop().create_task(daemon.stop())


async def main():
    # Register OS signal handlers for graceful termination
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for s in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(daemon.stop()))
    else:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    await daemon.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("daemon_interrupted_by_keyboard")
