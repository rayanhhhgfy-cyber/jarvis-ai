# ====================================================================
# JARVIS OMEGA — Clip Machine Service Unit Tests
# ====================================================================
"""
Unit tests for ClipMachineService, mocking transcription, highlight detection,
FFmpeg cutting operations, and virality scoring.
"""

import json
import pytest
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from backend.services.clip_machine_service import ClipMachineService, CLIP_JOBS

TEST_CLIPS_DIR = Path("./workspace/test_clips_temp")

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def clip_svc():
    if TEST_CLIPS_DIR.exists():
        shutil.rmtree(TEST_CLIPS_DIR)
    TEST_CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    
    with patch("backend.services.clip_machine_service.settings") as mock_settings:
        mock_settings.workspace_dir = str(TEST_CLIPS_DIR)
        
        service = ClipMachineService()
        yield service
        
    if TEST_CLIPS_DIR.exists():
        shutil.rmtree(TEST_CLIPS_DIR)

@pytest.mark.anyio
@patch("backend.services.clip_machine_service.transcription_service")
@patch("backend.services.clip_machine_service.llm_service")
async def test_clip_machine_pipeline(mock_llm, mock_transcribe, clip_svc):
    """Test full clip machine pipeline from upload to highlight extraction and scoring."""
    # 1. Upload mock video
    original_video_data = b"fake video bytes"
    filename = "test_gameplay.mp4"
    job = await clip_svc.upload_video(filename, original_video_data)
    
    assert job.status == "uploaded"
    assert job.job_id.startswith("clip_")
    assert Path(job.video_path).exists()
    
    # 2. Mock Whisper transcription response
    mock_transcribe.transcribe_file = AsyncMock(return_value="Hello world this is some amazing gameplay. Look at this triple kill!")
    
    # Mock video duration check
    clip_svc._get_video_duration = AsyncMock(return_value=60.0)

    
    # Mock LLM highlight detection JSON
    mock_llm.get_response = AsyncMock(side_effect=[
        # Call 1: detect_highlights
        json.dumps([
            {
                "start": 5.0,
                "end": 15.0,
                "title": "Amazing Triple Kill",
                "reason": "High action moment with excitement",
                "score": 95.0
            }
        ]),
        # Call 2: score_virality (overall scoring)
        json.dumps({
            "hook_strength": 90,
            "pacing": 85,
            "emotion": 95,
            "shareability": 80,
            "overall": 88,
            "reasoning": "High emotional response"
        })
    ])
    
    # Mock FFmpeg / FFprobe subprocess calls to avoid actual system video cutting
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc
        
        # Override ffmpeg path to test it
        clip_svc._ffmpeg = "ffmpeg"
        clip_svc._ffprobe = "ffprobe"
        
        # Run pipeline
        res_job = await clip_svc.process_video(job.job_id, platforms=["tiktok"])
        
        assert res_job.status == "complete"
        assert len(res_job.highlights) == 1
        assert res_job.highlights[0].title == "Amazing Triple Kill"
        
        # Assert clips metadata was updated
        assert len(res_job.clips) == 1
        clip = res_job.clips[0]
        assert clip.title == "Amazing Triple Kill"
        assert clip.platform == "tiktok"
        assert clip.viral_score is not None
        assert clip.viral_score.overall == 88
