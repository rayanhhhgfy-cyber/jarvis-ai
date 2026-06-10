# ====================================================================
# JARVIS OMEGA — Voice Message Service (gTTS)
# ====================================================================
"""
Generates voice message audio files using Google Text-to-Speech (gTTS)
for sending as Instagram voice messages. Supports Arabic and English.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from gtts import gTTS
from shared.logger import get_logger

log = get_logger("voice_service")

_TEMP_DIR = Path(tempfile.gettempdir()) / "jarvis_voice"
_MAX_OLD_FILES = 50


class VoiceService:
    def __init__(self) -> None:
        self._available = True
        _TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_files()

    def generate_voice(self, text: str, lang: str = "ar") -> Optional[Path]:
        """Generate an MP3 voice message file from text.

        Args:
            text: Text to speak.
            lang: Language code ('ar' for Arabic, 'en' for English).

        Returns:
            Path to the temporary MP3 file, or None on failure.
        """
        try:
            filename = f"voice_{uuid.uuid4().hex[:12]}.mp3"
            filepath = _TEMP_DIR / filename

            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(str(filepath))

            if filepath.stat().st_size < 100:
                log.warning("voice_generated_too_small", path=str(filepath))
                filepath.unlink(missing_ok=True)
                return None

            log.info("voice_generated", lang=lang, chars=len(text), path=str(filepath))
            self._cleanup_old_files()
            return filepath

        except Exception as e:
            log.error("voice_generation_failed", error=str(e), lang=lang)
            return None

    def detect_language(self, text: str) -> str:
        """Simple heuristic: returns 'ar' if text contains Arabic chars, else 'en'."""
        import re
        if re.search(r"[\u0600-\u06FF]", text):
            return "ar"
        return "en"

    def _cleanup_old_files(self) -> None:
        """Remove old temp voice files to avoid filling disk."""
        try:
            files = sorted(_TEMP_DIR.iterdir(), key=lambda p: p.stat().st_mtime)
            while len(files) > _MAX_OLD_FILES:
                files[0].unlink(missing_ok=True)
                files = files[1:]
        except Exception:
            pass


voice_service = VoiceService()
