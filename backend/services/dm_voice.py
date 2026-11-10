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
# Max characters in ONE voice message. Instagram caps a voice message at
# about a minute (1 minute on iOS, up to 5 on some Android) — 450 chars
# is roughly half a minute of speech in either language, so every chunk
# fits with room to spare. A longer reply is sent as several voice
# notes in a row, never cut off mid-sentence.
_CHUNK_CHARS = 450
# Split after a sentence-ending mark (English + Arabic) or a newline.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟۔])\s+|\n+")


def _pick_voice(text: str) -> str:
    """Arabic voice for Arabic text, English voice otherwise."""
    return _AR_VOICE if _ARABIC_RE.search(text or "") else _EN_VOICE


def _split_text(text: str) -> list[str]:
    """Split a reply into chunks that each fit in one voice message.

    Splits at sentence ends and packs sentences into chunks of at most
    ``_CHUNK_CHARS``. A single over-long sentence is split at word
    boundaries, never mid-word. Joining the chunks with a space gives
    back the original text.
    """
    text = (text or "").strip()
    if not text:
        return []
    sentences = [
        s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()
    ]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > _CHUNK_CHARS:
            # Over-long sentence: flush what we have, then split it
            # at word boundaries into full chunks.
            if current:
                chunks.append(current)
                current = ""
            buf = ""
            for word in sentence.split():
                piece = f"{buf} {word}".strip() if buf else word
                if len(piece) > _CHUNK_CHARS:
                    if buf:
                        chunks.append(buf)
                    buf = word
                    # One word longer than a chunk (a long URL): hard-cut it.
                    while len(buf) > _CHUNK_CHARS:
                        chunks.append(buf[:_CHUNK_CHARS])
                        buf = buf[_CHUNK_CHARS:]
                else:
                    buf = piece
            current = buf
            continue
        piece = f"{current} {sentence}".strip() if current else sentence
        if len(piece) > _CHUNK_CHARS:
            if current:
                chunks.append(current)
            current = sentence
        else:
            current = piece
    if current:
        chunks.append(current)
    return chunks


# Microsoft's newer Edge TTS server — same voices as the classic
# endpoint, used when the classic one answers 403 (it started doing
# that for many edge-tts apps in 2026, edge-tts #490; no upstream fix).
_NEW_EDGE_WSS_HOST = "api.msedgeservices.com"


async def _edge_tts_save(text: str, out_path: Path, new_server: bool = False) -> bool:
    """One Edge TTS attempt. Returns True when the MP3 is written.

    With new_server=True the websocket URL is pointed at Microsoft's
    newer server (api.msedgeservices.com) for the duration of the
    attempt, then restored — the classic endpoint is the default.
    """
    try:
        import edge_tts
        import edge_tts.communicate as _edge_comm
        from edge_tts import constants as _edge_const
    except ImportError:
        log.warning("dm_voice_no_edge_tts")
        return False
    patched = False
    old_url = None
    try:
        if new_server:
            old_url = _edge_comm.WSS_URL
            _edge_comm.WSS_URL = (
                f"wss://{_NEW_EDGE_WSS_HOST}/consumer/speech/synthesize/readaloud/edge/v1"
                f"?TrustedClientToken={_edge_const.TRUSTED_CLIENT_TOKEN}"
            )
            patched = True
        communicate = edge_tts.Communicate(text, _pick_voice(text))
        await communicate.save(str(out_path))
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        log.warning("dm_voice_tts_failed", error=str(e))
        return False
    finally:
        if patched:
            _edge_comm.WSS_URL = old_url


def _gtts_write(text: str, lang: str, out_path: str) -> None:
    """Blocking gTTS write — always called via asyncio.to_thread."""
    from gtts import gTTS

    gTTS(text=text, lang=lang).save(out_path)


async def _gtts_save(text: str, out_path: Path) -> bool:
    """Google Translate TTS (free, no key) — the last resort when Edge
    TTS is blocked. Arabic gets lang 'ar', everything else 'en'."""
    try:
        from gtts import gTTS  # noqa: F401  (import check only)
    except ImportError:
        log.warning("dm_voice_no_gtts")
        return False
    lang = "ar" if _ARABIC_RE.search(text or "") else "en"
    try:
        await asyncio.to_thread(_gtts_write, text, lang, str(out_path))
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        log.warning("dm_voice_gtts_failed", error=str(e))
        return False


async def _synthesize_mp3(text: str) -> Path | None:
    """Text -> MP3 file. Returns the path, or None when every engine fails.

    Three layers, in order: Edge TTS on the classic endpoint, Edge TTS
    on Microsoft's newer server (when the classic one 403s), then
    Google Translate TTS. A voice reply goes out as long as any one of
    them works — the caller only falls back to text when all three fail.
    """
    text = (text or "").strip()
    if not text:
        return None
    tmpdir = Path(tempfile.mkdtemp(prefix="jarvis_voice_"))
    tmp = tmpdir / "reply.mp3"
    if await _edge_tts_save(text, tmp):
        return tmp
    if await _edge_tts_save(text, tmp, new_server=True):
        return tmp
    if await _gtts_save(text, tmp):
        return tmp
    try:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as e:
        log.warning("dm_voice_cleanup_failed", error=str(e))
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


async def _mp3_to_ogg(mp3_path: Path) -> Path | None:
    """ffmpeg MP3 -> OGG Opus (the only format Telegram voice accepts)."""
    ogg_path = mp3_path.with_suffix(".ogg")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error",
            "-i", str(mp3_path),
            "-c:a", "libopus", "-b:a", "64k",
            str(ogg_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("dm_voice_ffmpeg_failed", error=stderr.decode()[:200])
            return None
        if ogg_path.exists() and ogg_path.stat().st_size > 0:
            return ogg_path
        return None
    except Exception as e:
        log.warning("dm_voice_convert_failed", error=str(e))
        return None


async def send_voice_reply(client: object, thread_id: str, text: str) -> bool:
    """Synthesize the reply and send it as Instagram voice message(s).

    A reply of any length works: it is split into chunks that each fit
    in one voice message and sent in order. All audio is built BEFORE
    anything is sent — if any chunk fails to synthesize, nothing goes
    out and the caller falls back to text, so the person never gets a
    half-voice plus the full text. If a send fails after some chunks
    already went out, this returns False and the caller still sends the
    full text, so the reply arrives complete (with the first part
    duplicated as voice). ``client`` is an InstagramClient (which has
    send_voice). Temp files are always cleaned up.
    """
    chunks = _split_text(text)
    if not chunks:
        return False
    send_voice = getattr(client, "send_voice", None)
    if not send_voice:
        return False
    built: list[tuple[Path, Path]] = []
    tmpdirs: list[Path] = []
    try:
        for chunk in chunks:
            mp3_path = await _synthesize_mp3(chunk)
            if not mp3_path:
                return False
            tmpdirs.append(mp3_path.parent)
            m4a_path = await _mp3_to_m4a(mp3_path)
            if not m4a_path:
                return False
            built.append((mp3_path, m4a_path))
        for _, m4a_path in built:
            try:
                result = await send_voice(thread_id, m4a_path)
            except Exception as e:
                log.warning("dm_voice_send_failed", error=str(e))
                return False
            if not (result and result.get("ok")):
                return False
        return True
    except Exception as e:
        log.warning("dm_voice_send_failed", error=str(e))
        return False
    finally:
        # Clean up every chunk's temp dir (mp3 + m4a live together).
        try:
            import shutil

            for tmpdir in tmpdirs:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


async def send_telegram_voice_reply(text: str) -> bool:
    """Synthesize the reply and send it as Telegram voice message(s).

    Same rules as the Instagram voice reply: any length works (split
    into chunks, sent in order), all audio is built BEFORE anything is
    sent, and a failure returns False so the caller falls back to text.
    Telegram voice messages must be OGG Opus, so each chunk is
    converted with _mp3_to_ogg before sending.
    """
    from backend.services.telegram_notifier import send_telegram_voice

    chunks = _split_text(text)
    if not chunks:
        return False
    built: list[Path] = []
    tmpdirs: list[Path] = []
    try:
        for chunk in chunks:
            mp3_path = await _synthesize_mp3(chunk)
            if not mp3_path:
                return False
            tmpdirs.append(mp3_path.parent)
            ogg_path = await _mp3_to_ogg(mp3_path)
            if not ogg_path:
                return False
            built.append(ogg_path)
        for ogg_path in built:
            if not await send_telegram_voice(str(ogg_path)):
                return False
        return True
    except Exception as e:
        log.warning("dm_voice_telegram_send_failed", error=str(e))
        return False
    finally:
        try:
            import shutil

            for tmpdir in tmpdirs:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            log.warning("dm_voice_cleanup_failed", error=str(e))
