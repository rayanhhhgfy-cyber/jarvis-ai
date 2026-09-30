# ====================================================================
# JARVIS OMEGA — Autonomous Clip Machine Router
# ====================================================================
"""
FastAPI router for the Autonomous Clip Machine.
Provides endpoints for video upload, starting processing pipelines,
checking task status, listing history, and retrieving generated clips and thumbnails.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, File, UploadFile, BackgroundTasks, status
from fastapi.responses import FileResponse

from backend.services.clip_machine_service import clip_machine_service
from shared.logger import get_logger

log = get_logger("router_clips")
router = APIRouter(prefix="/api/clips", tags=["Clip Machine"])


class ProcessRequest(BaseModel):
    platforms: Optional[List[str]] = None


@router.post("/upload", response_model=Dict[str, Any])
async def upload_video(file: UploadFile = File(...)):
    """Upload a raw video file to start a clip extraction job."""
    try:
        content = await file.read()
        job = await clip_machine_service.upload_video(file.filename, content)
        return job.to_dict()
    except Exception as e:
        log.error("clip_upload_failed", filename=file.filename, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video upload failed: {str(e)}"
        )


@router.post("/{job_id}/process", response_model=Dict[str, Any])
async def process_video(job_id: str, req: ProcessRequest, background_tasks: BackgroundTasks):
    """Start the video processing pipeline (transcribe -> cut -> score) in the background."""
    job = clip_machine_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("uploaded", "error"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is already in state: {job.status}"
        )

    # Launch pipeline in background to prevent blocking
    background_tasks.add_task(clip_machine_service.process_video, job_id, req.platforms)
    
    # Update job state in-memory so UI knows it started
    job.status = "transcribing"
    job.progress = 5
    job.message = "Initializing background processing pipeline..."
    
    return job.to_dict()


@router.get("/history", response_model=List[Dict[str, Any]])
async def get_history():
    """Retrieve history of all clip processing jobs."""
    try:
        return clip_machine_service.get_all_jobs()
    except Exception as e:
        log.error("clip_history_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}/status", response_model=Dict[str, Any])
async def get_status(job_id: str):
    """Get status and progress of a clip processing job."""
    job = clip_machine_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/{job_id}/results", response_model=List[Dict[str, Any]])
async def get_results(job_id: str):
    """Get the list of generated clips and scores for a completed job."""
    job = clip_machine_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Map clips to dynamic API URLs so the frontend can load them
    results = []
    for clip in job.clips:
        clip_dict = clip.to_dict() if hasattr(clip, "to_dict") else {
            "clip_id": clip.clip_id,
            "filename": clip.filename,
            "path": clip.path,
            "start": clip.start,
            "end": clip.end,
            "duration": clip.duration,
            "title": clip.title,
            "transcript": clip.transcript,
            "platform": clip.platform,
            "viral_score": {
                "hook_strength": clip.viral_score.hook_strength,
                "pacing": clip.viral_score.pacing,
                "emotion": clip.viral_score.emotion,
                "shareability": clip.viral_score.shareability,
                "overall": clip.viral_score.overall,
                "reasoning": clip.viral_score.reasoning,
            } if clip.viral_score else None,
            "thumbnail_path": clip.thumbnail_path,
        }
        
        # Add frontend-accessible URLs
        clip_dict["video_url"] = f"/api/clips/{job_id}/video/{clip.clip_id}"
        clip_dict["thumbnail_url"] = f"/api/clips/{job_id}/thumbnail/{clip.clip_id}" if clip.thumbnail_path else None
        results.append(clip_dict)
        
    return results


@router.get("/{job_id}/video/{clip_id}")
async def get_clip_video(job_id: str, clip_id: str):
    """Stream/Download the generated MP4 clip."""
    file_path = await clip_machine_service.get_clip_file_path(job_id, clip_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Clip video file not found")
    
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=os.path.basename(file_path)
    )


@router.get("/{job_id}/thumbnail/{clip_id}")
async def get_clip_thumbnail(job_id: str, clip_id: str):
    """Get the generated JPEG thumbnail for a clip."""
    job = clip_machine_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    target_clip = None
    for clip in job.clips:
        if clip.clip_id == clip_id:
            target_clip = clip
            break
            
    if not target_clip or not target_clip.thumbnail_path or not os.path.exists(target_clip.thumbnail_path):
        raise HTTPException(status_code=404, detail="Clip thumbnail not found")
        
    return FileResponse(
        path=target_clip.thumbnail_path,
        media_type="image/jpeg",
        filename=os.path.basename(target_clip.thumbnail_path)
    )
