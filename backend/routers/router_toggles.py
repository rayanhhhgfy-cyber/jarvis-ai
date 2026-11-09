# ====================================================================
# JARVIS OMEGA — System Toggles Router
# ====================================================================
"""
REST endpoints for the chat-controlled runtime toggles
(``backend/services/system_toggles.py``).

* ``GET /api/toggles`` — current on/off state of every toggle.
* ``GET /api/toggles/{toggle_id}`` — state of one toggle.
* ``POST /api/toggles/{toggle_id}`` — request a change. This does NOT
  apply anything immediately: it creates an approval request and
  returns its ``approval_id``. Sir approves via the existing
  ``POST /api/approvals/{approval_id}/approve`` endpoint (or the
  dashboard approval card); a background task then applies the toggle
  only if approved. Denial / timeout changes nothing.

The dashboard chat is the primary surface (see ``router_chat``); this
router exists so the frontend can also render a toggles panel and
request changes through the same approval gate.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services import system_toggles
from shared.logger import get_logger

log = get_logger("router_toggles")
router = APIRouter(prefix="/api/toggles", tags=["System Toggles"])


class ToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Desired state: true = on, false = off.")
    timeout_seconds: float = Field(
        300.0, description="How long to wait for Sir's approval before giving up."
    )


@router.get("")
async def list_toggles() -> dict[str, Any]:
    """Current on/off state of every toggle."""
    return {"toggles": system_toggles.get_state()}


@router.get("/{toggle_id}")
async def get_toggle(toggle_id: str) -> dict[str, Any]:
    """Current state of one toggle."""
    try:
        return system_toggles.get_state(toggle_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown toggle '{toggle_id}'")


@router.post("/{toggle_id}", status_code=202)
async def request_toggle_change(toggle_id: str, req: ToggleRequest) -> dict[str, Any]:
    """Request a toggle change (approval-gated, applied only if approved)."""
    if toggle_id not in system_toggles.TOGGLES:
        raise HTTPException(status_code=404, detail=f"Unknown toggle '{toggle_id}'")
    result = await system_toggles.submit_toggle_request(
        toggle_id, req.enabled, timeout=req.timeout_seconds
    )
    log.info(
        "toggle_change_requested",
        toggle_id=toggle_id,
        desired=req.enabled,
        approval_id=result.get("approval_id"),
    )
    return result
