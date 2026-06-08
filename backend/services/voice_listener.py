from __future__ import annotations

import asyncio
import io
import queue
import struct
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from backend.services.desktop_service import desktop_service
from backend.services.tts_service import tts_service
from backend.websocket_manager import ws_manager
from shared.logger import get_logger

log = get_logger("voice_listener")

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
BLOCK_SIZE = 1024
SILENCE_DURATION = 1.5
MIN_SPEECH_DURATION = 0.5
ENERGY_THRESHOLD = 500


class VoiceListener:
    def __init__(self):
        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._transcribe_callback: Optional[Callable] = None
        self._on_wake_callback: Optional[Callable] = None

    def set_transcribe_callback(self, cb: Callable):
        self._transcribe_callback = cb

    def set_on_wake_callback(self, cb: Callable):
        self._on_wake_callback = cb

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("voice_listener_started")

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        log.info("voice_listener_stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _listen_loop(self):
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._audio_callback,
            )
            self._stream.start()

            speech_chunks = []
            is_speaking = False
            silence_start = 0.0

            while self._running:
                try:
                    data = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    if is_speaking and time.time() - silence_start > SILENCE_DURATION:
                        if speech_chunks:
                            self._process_speech(b"".join(speech_chunks))
                            speech_chunks = []
                        is_speaking = False
                    continue

                energy = np.sqrt(np.mean(np.square(data.astype(np.float64))))

                if energy > ENERGY_THRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        speech_chunks = []
                    speech_chunks.append(data.tobytes())
                    silence_start = time.time()
                else:
                    if is_speaking:
                        speech_chunks.append(data.tobytes())

        except Exception as e:
            log.error("voice_listener_loop_failed", error=str(e))
        finally:
            self._running = False

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.debug("audio_status", status=str(status))
        self._audio_queue.put(indata.copy())

    def _process_speech(self, audio_bytes: bytes):
        if not self._transcribe_callback:
            return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            text = loop.run_until_complete(self._transcribe_callback(audio_bytes))
            loop.close()
            if text and len(text.strip()) > 2:
                log.info("voice_transcribed", text=text[:100])
                self._check_wake_word(text)
        except Exception as e:
            log.debug("transcribe_failed", error=str(e))

    def _check_wake_word(self, text: str):
        lower = text.lower().strip()
        wake_phrases = ["wake up jarvis", "hey jarvis", "jarvis", "wake up", "hello jarvis", "jarvis wake up"]
        if any(phrase in lower for phrase in wake_phrases):
            log.info("wake_word_detected", text=text)
            try:
                async def wake_actions():
                    try:
                        await ws_manager.broadcast({
                            "type": "wake_word_detected",
                            "payload": {
                                "timestamp": datetime.utcnow().isoformat(),
                                "text": text,
                            },
                        })
                    except Exception:
                        pass
                    try:
                        bw = desktop_service.focus_window("Jarvis")
                        if not bw.get("success"):
                            bw = desktop_service.focus_window("Microsoft Edge")
                        if not bw.get("success"):
                            ss = desktop_service.get_screen_size()
                            if ss.get("success"):
                                try:
                                    from backend.services.desktop_cursor import cursor_overlay
                                    cursor_overlay.start()
                                    cursor_overlay.show(ss["width"] // 2, ss["height"] // 2, "#00FF88", "JARVIS Awake", duration=2.0)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    try:
                        await tts_service.generate_speech("Yes, Sir? How can I help you?", voice="jarvis")
                    except Exception:
                        pass

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(wake_actions())
                loop.close()
            except Exception as e:
                log.error("wake_action_failed", error=str(e))

            if self._on_wake_callback:
                try:
                    self._on_wake_callback(text)
                except Exception:
                    pass


voice_listener = VoiceListener()
