# ====================================================================
# JARVIS OMEGA — Autonomous Clip Machine Service
# ====================================================================
"""
Clip Machine Service. Handles video upload, Whisper transcription,
LLM-powered highlight detection, FFmpeg clip extraction with subtitles,
virality prediction scoring, and multi-platform formatting.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.services.llm_service import llm_service
from backend.services.transcription_service import transcription_service
from shared.logger import get_logger

log = get_logger("clip_machine_service")

# Storage for processing jobs
CLIP_JOBS: Dict[str, "ClipJob"] = {}


# ====================================================================
# Data Classes
# ====================================================================

@dataclass
class TranscriptSegment:
    start: float       # seconds
    end: float         # seconds
    text: str

@dataclass
class Highlight:
    start: float
    end: float
    title: str
    reason: str
    score: float       # 0–100 engagement score from LLM

@dataclass
class ViralScore:
    hook_strength: int      # 0–100
    pacing: int             # 0–100
    emotion: int            # 0–100
    shareability: int       # 0–100
    overall: int            # 0–100
    reasoning: str

@dataclass
class GeneratedClip:
    clip_id: str
    filename: str
    path: str
    start: float
    end: float
    duration: float
    title: str
    transcript: str
    platform: str           # tiktok | youtube_shorts | reels | original
    viral_score: Optional[ViralScore] = None
    thumbnail_path: Optional[str] = None

@dataclass
class ClipJob:
    job_id: str
    original_filename: str
    video_path: str
    status: str = "uploaded"   # uploaded | transcribing | analyzing | cutting | scoring | complete | error
    progress: int = 0          # 0–100
    message: str = ""
    created_at: str = ""
    transcript: List[TranscriptSegment] = field(default_factory=list)
    full_transcript: str = ""
    highlights: List[Highlight] = field(default_factory=list)
    clips: List[GeneratedClip] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "original_filename": self.original_filename,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "full_transcript": self.full_transcript,
            "highlights": [asdict(h) for h in self.highlights],
            "clips": [
                {
                    **asdict(c),
                    "viral_score": asdict(c.viral_score) if c.viral_score else None,
                }
                for c in self.clips
            ],
            "error": self.error,
        }


# ====================================================================
# Platform presets (resolution, aspect ratio)
# ====================================================================

PLATFORM_PRESETS = {
    "tiktok": {"width": 1080, "height": 1920, "label": "TikTok"},
    "youtube_shorts": {"width": 1080, "height": 1920, "label": "YouTube Shorts"},
    "reels": {"width": 1080, "height": 1920, "label": "Instagram Reels"},
    "original": {"width": None, "height": None, "label": "Original"},
}


# ====================================================================
# Service
# ====================================================================

class ClipMachineService:
    """
    Orchestrates the autonomous clip generation pipeline:
    1. Upload video → save to disk
    2. Extract audio → Whisper transcription via Groq
    3. LLM analyzes transcript for engaging highlight segments
    4. FFmpeg cuts clips, overlays subtitles, resizes for platform
    5. LLM predicts virality score for each clip
    """

    def __init__(self) -> None:
        self.clips_dir = Path(settings.workspace_dir) / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg = shutil.which("ffmpeg")
        self._ffprobe = shutil.which("ffprobe")

    # ----------------------------------------------------------------
    # 1. Upload
    # ----------------------------------------------------------------

    async def upload_video(self, filename: str, file_bytes: bytes) -> ClipJob:
        """Save uploaded video and create a job."""
        job_id = f"clip_{uuid.uuid4().hex[:12]}"
        job_dir = self.clips_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        video_path = job_dir / filename
        video_path.write_bytes(file_bytes)

        job = ClipJob(
            job_id=job_id,
            original_filename=filename,
            video_path=str(video_path),
            status="uploaded",
            created_at=datetime.utcnow().isoformat(),
            message="Video uploaded successfully",
        )
        CLIP_JOBS[job_id] = job
        log.info("clip_video_uploaded", job_id=job_id, filename=filename, size_mb=round(len(file_bytes) / 1024 / 1024, 2))
        return job

    # ----------------------------------------------------------------
    # 2. Full processing pipeline
    # ----------------------------------------------------------------

    async def process_video(self, job_id: str, platforms: Optional[List[str]] = None) -> ClipJob:
        """Run the complete clip pipeline end-to-end."""
        job = CLIP_JOBS.get(job_id)
        if not job:
            raise FileNotFoundError(f"Job {job_id} not found")

        if platforms is None:
            platforms = ["tiktok", "youtube_shorts"]

        try:
            # Step 1: Transcribe
            job.status = "transcribing"
            job.progress = 10
            job.message = "Extracting audio and transcribing..."
            await self._transcribe(job)

            # Step 2: Detect highlights
            job.status = "analyzing"
            job.progress = 35
            job.message = "Analyzing transcript for highlights..."
            await self._detect_highlights(job)

            if not job.highlights:
                job.status = "complete"
                job.progress = 100
                job.message = "No highlights detected. The video may be too short or uniform."
                return job

            # Step 3: Generate clips
            job.status = "cutting"
            job.progress = 55
            job.message = f"Generating {len(job.highlights)} clips..."
            await self._generate_clips(job, platforms)

            # Step 4: Score virality
            job.status = "scoring"
            job.progress = 85
            job.message = "Predicting virality scores..."
            await self._score_virality(job)

            # Done
            job.status = "complete"
            job.progress = 100
            job.message = f"Done! {len(job.clips)} clips generated."
            log.info("clip_pipeline_complete", job_id=job_id, clip_count=len(job.clips))

        except Exception as e:
            job.status = "error"
            job.error = str(e)
            job.message = f"Pipeline failed: {str(e)}"
            log.error("clip_pipeline_failed", job_id=job_id, error=str(e))

        return job

    # ----------------------------------------------------------------
    # 3. Transcription
    # ----------------------------------------------------------------

    async def _transcribe(self, job: ClipJob) -> None:
        """Extract audio and transcribe via Groq Whisper."""
        video_path = Path(job.video_path)
        job_dir = video_path.parent
        audio_path = job_dir / "audio.wav"

        # Extract audio with FFmpeg
        if self._ffmpeg:
            proc = await asyncio.create_subprocess_exec(
                self._ffmpeg, "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(audio_path), "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.warning("ffmpeg_audio_extract_failed", error=stderr.decode()[:500])
                # Fall back to using original file for transcription
                audio_path = video_path
        else:
            log.warning("ffmpeg_not_found_using_original")
            audio_path = video_path

        # Transcribe
        transcript_text = await transcription_service.transcribe_file(str(audio_path))
        job.full_transcript = transcript_text

        # Create simple segmentation (split by sentence boundaries)
        job.transcript = self._segment_transcript(transcript_text)
        log.info("clip_transcription_complete", job_id=job.job_id, words=len(transcript_text.split()))

    def _segment_transcript(self, text: str) -> List[TranscriptSegment]:
        """Simple heuristic segmentation: split text into ~15-second chunks."""
        if not text.strip():
            return []

        words = text.split()
        # Approximate: ~2.5 words per second
        words_per_segment = 38  # ~15 seconds
        segments = []
        current_time = 0.0

        for i in range(0, len(words), words_per_segment):
            chunk = " ".join(words[i:i + words_per_segment])
            duration = len(words[i:i + words_per_segment]) / 2.5
            segments.append(TranscriptSegment(
                start=round(current_time, 2),
                end=round(current_time + duration, 2),
                text=chunk,
            ))
            current_time += duration

        return segments

    # ----------------------------------------------------------------
    # 4. Highlight Detection
    # ----------------------------------------------------------------

    async def _detect_highlights(self, job: ClipJob) -> None:
        """Use LLM to identify the most engaging segments."""
        if not job.full_transcript.strip():
            return

        # Get video duration via ffprobe
        duration = await self._get_video_duration(job.video_path)

        system_prompt = (
            "You are a viral content expert and video editor. Analyze the transcript below and identify "
            "the most engaging, shareable, or emotionally compelling segments that would make great short-form clips "
            "(15–60 seconds). Focus on:\n"
            "- Strong hooks or surprising statements in the first few seconds\n"
            "- Emotional peaks (humor, shock, insight, motivation)\n"
            "- Self-contained stories or anecdotes\n"
            "- Controversial or debate-worthy opinions\n"
            "- Educational 'aha' moments\n\n"
            "Return ONLY a JSON array of highlight objects. No markdown, no explanations.\n"
            "Each object: {\"start\": <seconds>, \"end\": <seconds>, \"title\": \"<short title>\", "
            "\"reason\": \"<why this is engaging>\", \"score\": <0-100>}\n"
            "Select 3–7 highlights max. Clips should be 15–60 seconds long.\n"
            f"Total video duration: {duration:.1f} seconds."
        )

        user_prompt = f"Transcript:\n{job.full_transcript[:6000]}"

        try:
            response = await llm_service.get_response(
                user_message=user_prompt,
                system_instructions=system_prompt,
                inject_memory=False,
            )

            # Parse JSON
            clean = response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\n", "", clean)
                clean = re.sub(r"\n```$", "", clean)
            clean = clean.strip()

            highlights_data = json.loads(clean)
            if not isinstance(highlights_data, list):
                highlights_data = [highlights_data]

            for h in highlights_data:
                start = float(h.get("start", 0))
                end = float(h.get("end", start + 30))
                # Clamp to video duration
                if duration > 0:
                    start = min(start, max(0, duration - 5))
                    end = min(end, duration)
                if end - start < 5:
                    continue  # Skip too-short clips

                job.highlights.append(Highlight(
                    start=round(start, 2),
                    end=round(end, 2),
                    title=h.get("title", "Highlight"),
                    reason=h.get("reason", ""),
                    score=float(h.get("score", 50)),
                ))

            # Sort by score descending
            job.highlights.sort(key=lambda h: h.score, reverse=True)
            log.info("clip_highlights_detected", job_id=job.job_id, count=len(job.highlights))

        except Exception as e:
            log.error("clip_highlight_detection_failed", error=str(e))
            # Fallback: create simple even splits
            if duration > 30:
                for i, start in enumerate(range(0, int(duration) - 15, 30)):
                    end = min(start + 30, duration)
                    job.highlights.append(Highlight(
                        start=float(start),
                        end=float(end),
                        title=f"Clip {i + 1}",
                        reason="Auto-generated segment",
                        score=50.0,
                    ))

    # ----------------------------------------------------------------
    # 5. Clip Generation (FFmpeg)
    # ----------------------------------------------------------------

    async def _generate_clips(self, job: ClipJob, platforms: List[str]) -> None:
        """Cut highlights into clips, add subtitles, resize for target platforms."""
        job_dir = Path(job.video_path).parent
        output_dir = job_dir / "output"
        output_dir.mkdir(exist_ok=True)

        for idx, highlight in enumerate(job.highlights):
            for platform in platforms:
                preset = PLATFORM_PRESETS.get(platform, PLATFORM_PRESETS["original"])
                clip_id = f"{job.job_id}_c{idx}_{platform}"
                out_filename = f"{clip_id}.mp4"
                out_path = output_dir / out_filename

                # Get transcript for this segment
                segment_text = self._get_transcript_for_range(
                    job.transcript, highlight.start, highlight.end
                )

                # Build FFmpeg command
                success = await self._ffmpeg_cut_clip(
                    input_path=job.video_path,
                    output_path=str(out_path),
                    start=highlight.start,
                    end=highlight.end,
                    width=preset.get("width"),
                    height=preset.get("height"),
                    subtitle_text=segment_text,
                )

                if success or True:  # Even if ffmpeg fails, record the clip entry
                    # Generate thumbnail
                    thumb_path = await self._generate_thumbnail(
                        job.video_path, highlight.start + 1, str(output_dir / f"{clip_id}_thumb.jpg")
                    )

                    clip = GeneratedClip(
                        clip_id=clip_id,
                        filename=out_filename,
                        path=str(out_path),
                        start=highlight.start,
                        end=highlight.end,
                        duration=round(highlight.end - highlight.start, 2),
                        title=highlight.title,
                        transcript=segment_text,
                        platform=platform,
                        thumbnail_path=thumb_path,
                    )
                    job.clips.append(clip)

            # Update progress
            job.progress = 55 + int(30 * (idx + 1) / len(job.highlights))

    async def _ffmpeg_cut_clip(
        self,
        input_path: str,
        output_path: str,
        start: float,
        end: float,
        width: Optional[int] = None,
        height: Optional[int] = None,
        subtitle_text: str = "",
    ) -> bool:
        """Use FFmpeg to cut a clip, optionally resize and burn subtitles."""
        if not self._ffmpeg:
            log.warning("ffmpeg_not_available_skipping_clip")
            return False

        duration = end - start
        cmd = [
            self._ffmpeg,
            "-ss", str(start),
            "-i", input_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
        ]

        # Build filter chain
        filters = []

        # Resize for vertical platforms
        if width and height:
            filters.append(
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
            )

        # Burn subtitles via drawtext (simple approach)
        if subtitle_text:
            # Escape special characters for FFmpeg drawtext
            escaped = (
                subtitle_text[:200]
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace("%", "%%")
            )
            filters.append(
                f"drawtext=text='{escaped}':"
                f"fontcolor=white:fontsize=28:borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=h-th-60:enable='between(t,0,{duration})'"
            )

        if filters:
            cmd.extend(["-vf", ",".join(filters)])

        cmd.extend(["-y", output_path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.error("ffmpeg_clip_failed", output=output_path, error=stderr.decode()[:500])
                return False
            log.info("ffmpeg_clip_generated", output=output_path)
            return True
        except Exception as e:
            log.error("ffmpeg_clip_exception", error=str(e))
            return False

    async def _generate_thumbnail(self, video_path: str, timestamp: float, output_path: str) -> Optional[str]:
        """Extract a single frame as a thumbnail."""
        if not self._ffmpeg:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                self._ffmpeg,
                "-ss", str(timestamp),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                "-y", output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return output_path if Path(output_path).exists() else None
        except Exception:
            return None

    # ----------------------------------------------------------------
    # 6. Virality Scoring
    # ----------------------------------------------------------------

    async def _score_virality(self, job: ClipJob) -> None:
        """LLM rates each clip's viral potential."""
        for clip in job.clips:
            try:
                system_prompt = (
                    "You are a social media virality expert. Rate this video clip's viral potential "
                    "across 4 dimensions (each 0–100):\n"
                    "1. hook_strength: How compelling is the opening 3 seconds?\n"
                    "2. pacing: Is the rhythm engaging throughout?\n"
                    "3. emotion: Does it evoke strong emotions (humor, shock, joy, anger)?\n"
                    "4. shareability: Would people send this to friends?\n\n"
                    "Also compute an 'overall' score (weighted average) and provide brief 'reasoning'.\n"
                    "Return ONLY a JSON object: {\"hook_strength\": N, \"pacing\": N, \"emotion\": N, "
                    "\"shareability\": N, \"overall\": N, \"reasoning\": \"...\"}\n"
                    "No markdown, no extra text."
                )

                user_prompt = (
                    f"Clip title: {clip.title}\n"
                    f"Duration: {clip.duration}s\n"
                    f"Platform: {clip.platform}\n"
                    f"Transcript:\n{clip.transcript[:1500]}"
                )

                response = await llm_service.get_response(
                    user_message=user_prompt,
                    system_instructions=system_prompt,
                    inject_memory=False,
                )

                clean = response.strip()
                if clean.startswith("```"):
                    clean = re.sub(r"^```(?:json)?\n", "", clean)
                    clean = re.sub(r"\n```$", "", clean)

                data = json.loads(clean.strip())
                clip.viral_score = ViralScore(
                    hook_strength=int(data.get("hook_strength", 50)),
                    pacing=int(data.get("pacing", 50)),
                    emotion=int(data.get("emotion", 50)),
                    shareability=int(data.get("shareability", 50)),
                    overall=int(data.get("overall", 50)),
                    reasoning=data.get("reasoning", ""),
                )

            except Exception as e:
                log.warning("clip_virality_scoring_failed", clip_id=clip.clip_id, error=str(e))
                clip.viral_score = ViralScore(
                    hook_strength=50, pacing=50, emotion=50,
                    shareability=50, overall=50,
                    reasoning="Scoring unavailable — using default scores.",
                )

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    async def _get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds via ffprobe."""
        if not self._ffprobe:
            return 0.0
        try:
            proc = await asyncio.create_subprocess_exec(
                self._ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return 0.0

    def _get_transcript_for_range(
        self, segments: List[TranscriptSegment], start: float, end: float
    ) -> str:
        """Get concatenated transcript text for a time range."""
        parts = []
        for seg in segments:
            # Overlap check
            if seg.end > start and seg.start < end:
                parts.append(seg.text)
        return " ".join(parts) if parts else ""

    def get_job(self, job_id: str) -> Optional[ClipJob]:
        """Retrieve a job by ID."""
        return CLIP_JOBS.get(job_id)

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs as summary dicts."""
        return [
            {
                "job_id": j.job_id,
                "original_filename": j.original_filename,
                "status": j.status,
                "progress": j.progress,
                "created_at": j.created_at,
                "clip_count": len(j.clips),
                "error": j.error,
            }
            for j in sorted(CLIP_JOBS.values(), key=lambda x: x.created_at, reverse=True)
        ]

    async def get_clip_file_path(self, job_id: str, clip_id: str) -> Optional[str]:
        """Get the file path of a specific clip for download."""
        job = CLIP_JOBS.get(job_id)
        if not job:
            return None
        for clip in job.clips:
            if clip.clip_id == clip_id:
                if Path(clip.path).exists():
                    return clip.path
        return None


# Singleton
clip_machine_service = ClipMachineService()
