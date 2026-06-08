# ====================================================================
# JARVIS OMEGA — Focus Mode Router
# ====================================================================
"""
API endpoints for activating, deactivating, and checking the status of Focus Mode.
Provides real missed message summaries upon deactivation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.focus_mode import focus_mode_service
from shared.logger import get_logger

log = get_logger("router_focus")
router = APIRouter(prefix="/api/focus", tags=["Focus Mode"])


class FocusActivateRequest(BaseModel):
    note: str
    duration_minutes: Optional[int] = None


@router.get("/status")
async def get_focus_status() -> Dict[str, Any]:
    """Retrieve current Focus Mode status, remaining time, and active configurations."""
    return focus_mode_service.get_status()


@router.post("/activate")
async def activate_focus(req: FocusActivateRequest) -> Dict[str, Any]:
    """Activate Focus Mode with a note and optional duration."""
    focus_mode_service.activate(req.note, duration_minutes=req.duration_minutes)
    return focus_mode_service.get_status()


@router.post("/deactivate")
async def deactivate_focus() -> Dict[str, Any]:
    """Deactivate Focus Mode and return queued messages plus an LLM summary."""
    result = focus_mode_service.deactivate()
    summary = ""
    if result.get("queued_count", 0) > 0:
        try:
            summary = await focus_mode_service.generate_queued_summary()
        except Exception as e:
            log.error("failed_to_generate_summary_in_router", error=str(e))
            summary = f"Sir, you missed {result.get('queued_count')} messages."
            
    return {
        "status": focus_mode_service.get_status(),
        "queued_count": result.get("queued_count", 0),
        "queued_messages": result.get("queued_messages", []),
        "summary": summary,
    }
