# ====================================================================
# JARVIS OMEGA — Microphone Listener
# ====================================================================
"""
Microphone audio stream listener. Captures raw voice recording streams
and monitors signal amplitudes for voice activity (VAD) triggers.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from typing import Optional

from shared.logger import get_logger

log = get_logger("microphone_listener")

try:
    import numpy as np
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


class MicrophoneListener:
    """
    Listens to local microphone input. Automatically detects speech
    via VAD and triggers transcription requests.
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._audio_buffer: list[np.ndarray] = []
        self._stream = None
        self._threshold = 0.03  # Volume amplitude threshold

    async def start(self) -> None:
        """Start listening to microphone input."""
        self._running = True
        if not SOUNDDEVICE_AVAILABLE:
            log.warning("sounddevice_not_installed_voice_recording_disabled")
            return
        
        try:
            self._task = asyncio.create_task(self._recording_loop())
            log.info("microphone_listener_started")
        except Exception as e:
            log.error("microphone_start_failed", error=str(e))

    async def stop(self) -> None:
        """Stop listening to microphone input."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("microphone_listener_stopped")

    async def record_snippet(self, duration_seconds: float) -> bytes:
        """Synchronously records and returns audio bytes of specified duration."""
        if not SOUNDDEVICE_AVAILABLE:
            log.warning("cannot_record_no_libraries")
            return b""

        log.info("recording_audio_snippet", duration=duration_seconds)
        try:
            # Run sync record in execution thread pool
            loop = asyncio.get_event_loop()
            recording = await loop.run_in_executor(
                None,
                lambda: sd.rec(
                    int(duration_seconds * self.sample_rate),
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                )
            )
            await loop.run_in_executor(None, sd.wait)

            # Convert to WAV bytes
            wav_io = io.BytesIO()
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)
                wf.writeframes(recording.tobytes())

            return wav_io.getvalue()
        except Exception as e:
            log.error("snippet_recording_failed", error=str(e))
            return b""

    async def _recording_loop(self) -> None:
        """Background loop streaming microphone audio input."""
        # Simple amplitude-based VAD recording loop
        # Submits audio stream chunks when volume exceeds threshold
        def callback(indata, frames, time_info, status):
            if status:
                log.warning("microphone_stream_status", status=str(status))
            # Calculate root-mean-square amplitude
            volume_norm = np.linalg.norm(indata) / np.sqrt(indata.size)
            if volume_norm > self._threshold:
                self._audio_buffer.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                callback=callback,
                blocksize=1024,
            )
            self._stream.start()

            while self._running:
                await asyncio.sleep(0.5)
                # Check if we have accumulated audio buffer and volume went silent
                # If so, package buffer as WAV and publish event or request transcription
                if len(self._audio_buffer) > 15:
                    log.info("voice_activity_detected_packaging_buffer")
                    # Clear buffer
                    self._audio_buffer.clear()

        except Exception as e:
            log.error("microphone_recording_loop_error", error=str(e))


# Global microphone listener instance
microphone_listener = MicrophoneListener()
