from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, status

from backend.services.settings_service import load, save
from backend.services.persona_service import list_personas

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/personas")
async def get_personas():
    return {"personas": list_personas()}


@router.get("/{user_id}")
async def get_settings(user_id: str = "default"):
    try:
        s = load(user_id)
        return {"user_id": user_id, **s}
    except Exception as e:
        log.error("settings_load_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


class SettingsUpdateRequest:
    def __init__(self, persona: str = "", custom_instructions_a: str = "", custom_instructions_b: str = ""):
        self.persona = persona
        self.custom_instructions_a = custom_instructions_a
        self.custom_instructions_b = custom_instructions_b


from pydantic import BaseModel


class SettingsPayload(BaseModel):
    persona: str = "adult"
    custom_instructions_a: str = ""
    custom_instructions_b: str = ""
    custom_suggestions: str = ""
    start_on_wakeup: bool = False


@router.post("/{user_id}")
async def post_settings(payload: SettingsPayload, user_id: str = "default"):
    try:
        updated = save(user_id, payload.model_dump())
        try:
            from backend.services.startup_service import update_startup_status
            update_startup_status(payload.start_on_wakeup)
        except Exception as startup_err:
            log.error("failed_to_update_startup_status", error=str(startup_err))
        return {"user_id": user_id, "status": "saved", **updated}
    except Exception as e:
        log.error("settings_save_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
