# ====================================================================
# JARVIS OMEGA — Wake Word Detector
# ====================================================================
"""
Wake word detection: monitors microphone input streams looking for
"Hey Jarvis" or "Jarvis" triggers. Uses Picovoice Porcupine if configured,
falling back to pure offline VAD detection.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Callable

from backend.config import settings
from shared.logger import get_logger

log = get_logger("wakeword_detector")

try:
    import pvporcupine
    PICOVOICE_AVAILABLE = True
except ImportError:
    PICOVOICE_AVAILABLE = False


class WakeWordDetector:
    """
    Monitors speech streams for wake word triggers.
    Runs locally and triggers a callback when active.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callback: Optional[Callable[[], Any]] = None

    def register_callback(self, callback: Callable[[], Any]) -> None:
        """Register the function to run when the wake word is detected."""
        self._callback = callback

    async def start(self) -> None:
        """Start listening for the wake word."""
        self._running = True
        self._task = asyncio.create_task(self._detection_loop())
        log.info("wakeword_detector_started")

    async def stop(self) -> None:
        """Stop listening for the wake word."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("wakeword_detector_stopped")

    async def _detection_loop(self) -> None:
        """Core wake word detection loop."""
        access_key = settings.picovoice_access_key

        if PICOVOICE_AVAILABLE and access_key:
            # Picovoice Porcupine integration
            try:
                log.info("initializing_porcupine_wakeword_detector")
                porcupine = pvporcupine.create(
                    access_key=access_key,
                    keywords=["jarvis", "hey jarvis"],
                )
                
                # Mock streaming frames
                while self._running:
                    # In a real setup, read audio frames from microphone stream
                    # and pass to porcupine.process(frame)
                    await asyncio.sleep(0.1)

            except Exception as e:
                log.error("porcupine_initialization_failed", error=str(e))
        else:
            log.warning("porcupine_unavailable_using_simulated_vad_trigger")

        # Simulated or manual detection trigger fallback
        while self._running:
            await asyncio.sleep(1.0)
            # In simulated mode we don't trigger callback automatically
            # unless a wake word test command is run
            pass

    def force_trigger(self) -> None:
        """Manually trigger the wake word callback (for tests)."""
        log.info("wakeword_force_triggered")
        if self._callback:
            if asyncio.iscoroutinefunction(self._callback):
                asyncio.create_task(self._callback())
            else:
                self._callback()


# Global wake word detector instance
wakeword_detector = WakeWordDetector()
