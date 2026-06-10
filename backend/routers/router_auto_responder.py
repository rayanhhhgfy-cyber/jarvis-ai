# ====================================================================
# JARVIS OMEGA — AutoResponder Router
# ====================================================================
"""
API endpoints for configuring and controlling the Smart AutoResponder.
"""

from fastapi import APIRouter, HTTPException

from backend.services.auto_responder import auto_responder_service
from pydantic import BaseModel
from typing import Optional

from shared.logger import get_logger

log = get_logger("router_auto_responder")
router = APIRouter(prefix="/api/auto-responder", tags=["AutoResponder"])


class AutoResponderSettings(BaseModel):
    timeout_minutes: Optional[int] = None
    active: Optional[bool] = None


@router.get("/status")
async def get_status():
    """Return current AutoResponder status and settings."""
    try:
        return auto_responder_service.get_settings()
    except Exception as e:
        log.error("auto_responder_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings")
async def update_settings(body: AutoResponderSettings):
    """Update AutoResponder timeout and/or toggle on/off."""
    try:
        return auto_responder_service.update_settings(
            timeout_minutes=body.timeout_minutes,
            active=body.active,
        )
    except Exception as e:
        log.error("auto_responder_settings_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle")
async def toggle():
    """Toggle AutoResponder on/off."""
    try:
        new_active = not auto_responder_service.is_active()
        return auto_responder_service.update_settings(active=new_active)
    except Exception as e:
        log.error("auto_responder_toggle_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
