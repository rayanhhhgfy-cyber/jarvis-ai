# ====================================================================
# JARVIS OMEGA — DM Voice Replies (Jarvis talks back, not just texts)
# ====================================================================
"""
Turns a reply into a voice note and sends it on Instagram.

* Speech: Microsoft Edge TTS (free, no key) — an Arabic male voice
  (ar-SA-HamedNeural) when the text is Arabic, an English male voice
  (en-US-ChristopherNeural) otherwise.
* Format: Instagram voice messages MUST be AAC in an MP4 container
  (.m4a). edge-tts produces MP3, so ffmpeg converts it.
* Fallback: anything that fails (TTS, conversion, send) returns False
  and the caller sends the text reply instead — a voice reply never
  breaks a DM reply.

ffmpeg must be installed on the server (Render buildCommand installs it).
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

from shared.logger import get_logger

log = get_logger("dm_voice")

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_EN_VOICE = "en-US-ChristopherNeural"
_AR_VOICE = "ar-SA-HamedNeural"
_MAX_CHARS = 500


def _pick_voice(text: str) -> str:
    """Arabic voice for Arabic text, English voice otherwise."""
    return _AR_VOICE if _ARABIC_RE.search(text or "") else _EN_VOICE


async def _synthesize_mp3(text: str) -> Path | None:
    """edge-tts -> MP3 file. Returns the path, or None on failure."""
    try:
        import edge_tts
    except ImportError:
        log.warning("dm_voice_no_edge_tts")
        return None
    text = (text or "").strip()[:_MAX_CHARS]
    if not text:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_voice_")) / "reply.mp3"
    try:
        communicate = edge_tts.Communicate(text, _pick_voice(text))
        await communicate.save(str(tmp))
        if tmp.exists() and tmp.stat().st_size > 0:
            return tmp
        return None
    except Exception as e:
        log.warning("dm_voice_tts_failed", error=str(e))
        return None


async def _mp3_to_m4a(mp3_path: Path) -> Path | None:
    """ffmpeg MP3 -> M4A/AAC (the only format Instagram voice accepts)."""
    m4a_path = mp3_path.with_suffix(".m4a")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error",
            "-i", str(mp3_path),
            "-c:a", "aac", "-b:a", "64k",
            str(m4a_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("dm_voice_ffmpeg_failed", error=stderr.decode()[:200])
            return None
        if m4a_path.exists() and m4a_path.stat().st_size > 0:
            return m4a_path
        return None
    except Exception as e:
        log.warning("dm_voice_convert_failed", error=str(e))
        return None


async def send_voice_reply(client: object, thread_id: str, text: str) -> bool:
    """Synthesize the reply and send it as an Instagram voice message.

    ``client`` is an InstagramClient (which has send_voice). Returns True
    when the voice message was sent; False on any failure (caller falls
    back to text). Temp files are always cleaned up.
    """
    mp3_path = await _synthesize_mp3(text)
    if not mp3_path:
        return False
    try:
        m4a_path = await _mp3_to_m4a(mp3_path)
        if not m4a_path:
            return False
        send_voice = getattr(client, "send_voice", None)
        if not send_voice:
            return False
        result = await send_voice(thread_id, m4a_path)
        return bool(result and result.get("ok"))
    except Exception as e:
        log.warning("dm_voice_send_failed", error=str(e))
        return False
    finally:
        # Clean up the temp dir (mp3 + m4a).
        try:
            import shutil

            shutil.rmtree(mp3_path.parent, ignore_errors=True)
        except Exception:
            pass
