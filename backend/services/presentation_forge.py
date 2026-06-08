"""
Presentation Forge — screen capture → frame stitching → narration → MP4.

# pip install: mss, moviepy, pyttsx3, numpy
# TERMUX-NOTE: mss needs X11 (may not work on Android/Termux).
#             Falls back to creating a silent slideshow.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from shared.logger import get_logger

log = get_logger("presentation_forge")


@dataclass
class Slide:
    title: str
    narration: str
    duration: float = 5.0  # seconds


class PresentationForge:
    """
    Creates MP4 presentations from screen captures + TTS narration.
    """

    def __init__(self):
        self._output_dir = Path.home() / "Downloads"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def create_presentation(self, slides: List[Slide], output_name: Optional[str] = None) -> Optional[str]:
        """
        Capture screen for each slide, generate TTS, stitch into MP4.
        Returns output file path or None on failure.
        """
        if not slides:
            log.warning("no_slides_provided")
            return None

        temp_dir = Path(tempfile.mkdtemp(prefix="pres_"))
        try:
            # Capture frames
            frames = await self._capture_frames(slides, temp_dir)

            # Generate narration audio
            audio_paths = await self._generate_narrations(slides, temp_dir)

            # Stitch to video
            output_name = output_name or f"presentation_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp4"
            output_path = str(self._output_dir / output_name)

            await self._stitch_video(frames, audio_paths, slides, output_path)
            log.info("presentation_created", output=output_path)
            return output_path
        except Exception as e:
            log.error("presentation_failed", error=str(e))
            return None
        finally:
            # Cleanup temp files
            import shutil
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    async def _capture_frames(self, slides: List[Slide], temp_dir: Path) -> List[str]:
        """Capture screen frames using mss."""
        frames = []
        for i, slide in enumerate(slides):
            try:
                import mss
                with mss.mss() as sct:
                    monitor = sct.monitors[1]  # Primary monitor
                    img = sct.grab(monitor)
                    path = str(temp_dir / f"slide_{i:03d}.png")
                    mss.tools.to_png(img.rgb, img.size, output=path)
                    frames.append(path)
            except Exception as e:
                log.debug("screen_capture_failed", index=i, error=str(e))
                # Create blank placeholder
                from PIL import Image
                img = Image.new("RGB", (1920, 1080), (30, 30, 30))
                path = str(temp_dir / f"slide_{i:03d}.png")
                img.save(path)
                frames.append(path)
        return frames

    async def _generate_narrations(self, slides: List[Slide], temp_dir: Path) -> List[str]:
        """Generate TTS audio files for each slide."""
        audio_paths = []
        for i, slide in enumerate(slides):
            try:
                import pyttsx3
                engine = pyttsx3.init()
                path = str(temp_dir / f"narration_{i:03d}.wav")
                engine.save_to_file(slide.narration, path)
                engine.runAndWait()
                audio_paths.append(path)
            except Exception as e:
                log.debug("tts_failed", index=i, error=str(e))
                audio_paths.append("")
        return audio_paths

    async def _stitch_video(
        self, frames: List[str], audio_paths: List[str],
        slides: List[Slide], output_path: str
    ) -> None:
        """Stitch frames and audio into MP4 using moviepy."""
        try:
            from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips

            clips = []
            for i, (frame_path, slide) in enumerate(zip(frames, slides)):
                clip = ImageClip(frame_path, duration=slide.duration)
                if audio_paths[i] and os.path.exists(audio_paths[i]):
                    try:
                        audio = AudioFileClip(audio_paths[i])
                        clip = clip.set_audio(audio)
                    except Exception:
                        pass
                clips.append(clip)

            if clips:
                final = concatenate_videoclips(clips, method="compose")
                final.write_videofile(output_path, fps=1, codec="libx264", audio_codec="aac", logger=None)
        except ImportError:
            log.warning("moviepy_not_installed — creating placeholder")
            Path(output_path).write_text("[Presentation Forge requires moviepy]")
        except Exception as e:
            log.error("stitch_failed", error=str(e))


presentation_forge = PresentationForge()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.presentation_forge import presentation_forge, Slide
# slides = [Slide("Intro", "Welcome to this presentation.", 5.0)]
# path = await presentation_forge.create_presentation(slides)
# print(path)
# ---
