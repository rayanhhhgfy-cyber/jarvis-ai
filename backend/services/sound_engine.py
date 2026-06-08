"""
JARVIS Sound Engine — async audio feedback layer.
Provides TTS alerts, tone beeps, and event-driven voice lines.
All other subsystems wire into this for audible feedback.

# pip install: pyttsx3 sounddevice numpy scipy
# pkg install: espeak portaudio termux-api
"""

from __future__ import annotations

import asyncio
import enum
import heapq
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from shared.logger import get_logger

log = get_logger("sound_engine")

# =========================================================================
# ENUMS
# =========================================================================


class SoundPriority(enum.IntEnum):
    CRITICAL = 0
    WARNING = 1
    INFO = 2


class JarvisEvent(enum.Enum):
    # System
    SERVER_START = "server_start"
    SERVER_DOWN = "server_down"
    SERVER_RESTART = "server_restart"
    # Debug / Recovery
    DEBUG_RETRY = "debug_retry"
    DEBUG_FAILED = "debug_failed"
    LAZARUS_TRIGGERED = "lazarus_triggered"
    # Memory
    MEMORY_PRUNING_COMPLETE = "memory_pruning_complete"
    CACHE_PURGE_COMPLETE = "cache_purge_complete"
    # Security
    VULNERABILITY_DETECTED = "vulnerability_detected"
    UNKNOWN_DEVICE_DETECTED = "unknown_device_detected"
    SUSPICIOUS_INPUT = "suspicious_input"
    # Database
    DB_CONNECTION_LOST = "db_connection_lost"
    DB_RECONNECTED = "db_reconnected"
    # Task
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    # Hardware
    WAKE_ON_LAN_SENT = "wake_on_lan_sent"
    DEVICE_UNREACHABLE = "device_unreachable"
    # General
    HEARTBEAT_LOST = "heartbeat_lost"
    FILE_SAVED = "file_saved"


# =========================================================================
# EVENT → VOICE LINE MAPPING
# =========================================================================

_EVENT_VOICE_LINES: dict[JarvisEvent, str] = {
    JarvisEvent.SERVER_START: "Jarvis systems online. All nominal, Sir.",
    JarvisEvent.SERVER_DOWN: "Warning. Core server connection lost. Initiating Lazarus protocol.",
    JarvisEvent.SERVER_RESTART: "Rebooting core systems. Stand by.",
    JarvisEvent.DEBUG_RETRY: "Retrying operation with adjusted parameters.",
    JarvisEvent.DEBUG_FAILED: "Debug sequence exhausted. Manual intervention required.",
    JarvisEvent.LAZARUS_TRIGGERED: "Lazarus protocol activated. Resurrecting core systems.",
    JarvisEvent.MEMORY_PRUNING_COMPLETE: "Memory consolidation complete. Redundant vectors pruned.",
    JarvisEvent.CACHE_PURGE_COMPLETE: "Transient cache purged. Storage optimized.",
    JarvisEvent.VULNERABILITY_DETECTED: "Security vulnerability detected in package dependencies. Immediate attention advised.",
    JarvisEvent.UNKNOWN_DEVICE_DETECTED: "Unknown device detected on local network. Investigate immediately.",
    JarvisEvent.SUSPICIOUS_INPUT: "Suspicious input pattern detected. Running isolation protocol.",
    JarvisEvent.DB_CONNECTION_LOST: "Database connection lost. Attempting reconnection.",
    JarvisEvent.DB_RECONNECTED: "Database connection reestablished. Systems nominal.",
    JarvisEvent.TASK_COMPLETED: "Task completed successfully, Sir.",
    JarvisEvent.TASK_FAILED: "Task execution failed. Review logs for details.",
    JarvisEvent.WAKE_ON_LAN_SENT: "Wake-on-LAN packet transmitted.",
    JarvisEvent.DEVICE_UNREACHABLE: "Device unreachable on network. Power cycling.",
    JarvisEvent.HEARTBEAT_LOST: "Heartbeat signal lost. Checking subsystems.",
    JarvisEvent.FILE_SAVED: "File saved. Running validation checks.",
}


# =========================================================================
# PRIORITY QUEUE ITEM
# =========================================================================


@dataclass(order=True)
class _SpeechItem:
    priority: int
    timestamp: float = field(compare=False)
    message: str = field(compare=False)
    event: Optional[JarvisEvent] = field(default=None, compare=False)


# =========================================================================
# SOUND ENGINE
# =========================================================================

_SAMPLE_RATE = 22050


class SoundEngine:
    """
    Async sound engine providing TTS alerts, tones, and event-driven voice.
    Higher-priority sounds interrupt lower-priority ones.
    """

    def __init__(self) -> None:
        self._queue: list[_SpeechItem] = []
        self._lock = asyncio.Lock()
        self._current_task: Optional[asyncio.Task] = None
        self._running = False
        self._tts_available = False
        self._audio_available = False
        self._engine = None

    # ------------------------------------------------------------------
    # INIT / TEARDOWN
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Probe for TTS and audio backends."""
        self._running = True
        self._probe_tts()
        self._probe_audio()
        log.info(
            "sound_engine_initialized",
            tts=self._tts_available,
            audio=self._audio_available,
        )

    def shutdown(self) -> None:
        self._running = False
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass
        log.info("sound_engine_shutdown")

    def _probe_tts(self) -> None:
        """Try pyttsx3 first, fall back to termux-tts-speak."""
        try:
            import pyttsx3  # type: ignore
            self._engine = pyttsx3.init(driverName="espeak")  # espeak backend
            self._engine.setProperty("rate", 160)
            self._engine.setProperty("volume", 0.9)
            self._engine.say("")
            self._engine.runAndWait()
            self._tts_available = True
            log.info("tts_backend_pyttsx3_ok")
        except Exception:
            # Fallback: check termux-tts-speak
            try:
                import subprocess
                subprocess.run(
                    ["termux-tts-speak", "test"],
                    capture_output=True,
                    timeout=3,
                )
                self._tts_available = True
                log.info("tts_backend_termux_ok")
            except Exception:
                log.warning("tts_backend_unavailable", hint="pkg install espeak termux-api")

    def _probe_audio(self) -> None:
        """Check sounddevice availability for tones."""
        try:
            import sounddevice  # type: ignore
            sounddevice.check_output_settings(device=None)
            self._audio_available = True
            log.info("audio_backend_ok")
        except Exception:
            log.warning("audio_backend_unavailable", hint="pip install sounddevice")

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    async def speak(self, message: str, priority: SoundPriority = SoundPriority.INFO) -> None:
        """Queue a TTS message. Higher priority interrupts current speech."""
        if not self._tts_available:
            return
        item = _SpeechItem(
            priority=int(priority),
            timestamp=time.time(),
            message=message,
        )
        async with self._lock:
            heapq.heappush(self._queue, item)
        self._schedule_next()

    async def play_tone(self, frequency: int, duration_ms: int) -> None:
        """Play a sine wave tone. Non-blocking."""
        if not self._audio_available:
            return
        try:
            import sounddevice  # type: ignore
            t = np.linspace(0, duration_ms / 1000, int(_SAMPLE_RATE * duration_ms / 1000), endpoint=False)
            wave = 0.3 * np.sin(2 * np.pi * frequency * t)
            sounddevice.play(wave, _SAMPLE_RATE, blocking=False)
        except Exception as e:
            log.debug("tone_play_failed", error=str(e))

    async def jarvis_startup_chime(self) -> None:
        """Play ascending C5→E5→G5 tone sequence on boot."""
        notes = [523, 659, 784]
        for freq in notes:
            await self.play_tone(freq, 200)
            await asyncio.sleep(0.15)
        await self.play_tone(1047, 400)

    async def jarvis_alert(self, event: JarvisEvent) -> None:
        """Map a typed system event to a voice alert + optional tone."""
        if event in (JarvisEvent.SERVER_DOWN, JarvisEvent.DEBUG_FAILED, JarvisEvent.VULNERABILITY_DETECTED):
            await self.play_tone(440, 300)
            await asyncio.sleep(0.1)
            await self.play_tone(350, 400)
        line = _EVENT_VOICE_LINES.get(event, f"Event: {event.value}")
        await self.speak(line, SoundPriority.CRITICAL if event in (
            JarvisEvent.SERVER_DOWN,
            JarvisEvent.VULNERABILITY_DETECTED,
            JarvisEvent.DEVICE_UNREACHABLE,
            JarvisEvent.DB_CONNECTION_LOST,
        ) else SoundPriority.WARNING)

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    def _schedule_next(self) -> None:
        if self._current_task and not self._current_task.done():
            return
        self._current_task = asyncio.create_task(self._process_queue())

    async def _process_queue(self) -> None:
        while self._running and self._queue:
            async with self._lock:
                item = heapq.heappop(self._queue)
            try:
                self._speak_sync(item.message)
            except Exception as e:
                log.error("tts_playback_failed", error=str(e))
            await asyncio.sleep(0.1)

    def _speak_sync(self, message: str) -> None:
        """Synchronous TTS call — runs in executor."""
        if self._engine:
            self._engine.say(message)
            self._engine.runAndWait()
        else:
            import subprocess
            subprocess.run(
                ["termux-tts-speak", message],
                capture_output=True,
                timeout=10,
            )


# Global singleton
sound_engine = SoundEngine()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.sound_engine import sound_engine, JarvisEvent, SoundPriority
# sound_engine.initialize()
# await sound_engine.jarvis_startup_chime()
# await sound_engine.speak("Systems nominal.", SoundPriority.INFO)
# await sound_engine.jarvis_alert(JarvisEvent.SERVER_DOWN)
# sound_engine.shutdown()
# ---
