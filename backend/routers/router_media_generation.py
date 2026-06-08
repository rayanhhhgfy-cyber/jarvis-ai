from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from backend.config import settings
from backend.services.media_generation_service import (
    generate_image,
    generate_video,
    list_generated,
)
from pydantic import BaseModel
from shared.logger import get_logger

log = get_logger("router_media_generation")
router = APIRouter(prefix="/api/media", tags=["Media Generation"])

GENERATED_DIR = Path(settings.storage_dir) / "media" / "generated"


class GenerateImageRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    size: Optional[str] = None


class GenerateVideoRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    duration: Optional[int] = None


@router.post("/generate/image")
async def api_generate_image(req: GenerateImageRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")
    result = await generate_image(
        prompt=req.prompt.strip(),
        model=req.model,
        size=req.size,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Image generation failed"))
    return result


@router.post("/generate/video")
async def api_generate_video(req: GenerateVideoRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")
    result = await generate_video(
        prompt=req.prompt.strip(),
        model=req.model,
        duration=req.duration,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Video generation failed"))
    return result


@router.get("/generated")
async def api_list_generated():
    files = await list_generated()
    return {"files": files, "count": len(files)}


@router.get("/generated/{filename}")
async def api_serve_generated(filename: str):
    safe_path = GENERATED_DIR / filename
    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if safe_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov"}:
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
        }.get(safe_path.suffix.lower(), "application/octet-stream")
        return FileResponse(str(safe_path), media_type=media_type)
    raise HTTPException(status_code=400, detail="Unsupported file type")


@router.get("/models")
async def api_list_models():
    from backend.services.media_generation_service import IMAGE_MODELS, VIDEO_MODELS
    return {
        "image_models": IMAGE_MODELS,
        "video_models": VIDEO_MODELS,
    }


@router.delete("/generated/{filename}")
async def api_delete_generated(filename: str):
    safe_path = GENERATED_DIR / filename
    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        safe_path.unlink()
        log.info("media_deleted", filename=filename)
        return {"success": True, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")
