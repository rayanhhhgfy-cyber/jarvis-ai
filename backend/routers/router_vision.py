# ====================================================================
# JARVIS OMEGA — Vision Router
# ====================================================================
"""
Vision processing routes: uploading screenshots/UI components for Qwen 2.5 VL
layout analysis and OCR text scanning.
"""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, status

from backend.services.vision_service import vision_service
from shared.logger import get_logger

log = get_logger("router_vision")
router = APIRouter(prefix="/api/vision", tags=["Vision"])

DEFAULT_VISION_PROMPT = (
    "Analyze this screenshot and identify all interactive UI elements, layout structures, "
    "and any text contents visible. Output a structured report."
)


@router.post("/analyze")
async def analyze_screenshot(
    file: UploadFile = File(..., description="Screenshot/Image file payload"),
    prompt: str = Query(DEFAULT_VISION_PROMPT, description="Custom instruction prompt for analysis"),
):
    """Processes visual screenshots and extracts layout positions, components, and OCR text."""
    log.info("vision_analyze_upload_received", file_name=file.filename)
    try:
        content = await file.read()
        analysis = await vision_service.analyze_image_bytes(content, prompt)
        return {"analysis": analysis}
    except Exception as e:
        log.error("upload_vision_analysis_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze screenshot: {str(e)}",
        )
