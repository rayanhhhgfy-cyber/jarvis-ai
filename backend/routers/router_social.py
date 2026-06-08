# ====================================================================
# JARVIS OMEGA — Social Reply Router
# ====================================================================
"""
API endpoints for cross-platform DM management.
Provides endpoints to scan unread messages, draft replies, send messages,
and auto-reply across Instagram, WhatsApp, Messenger, and X.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.social_reply_service import social_reply_service
from shared.logger import get_logger

log = get_logger("router_social")
router = APIRouter(prefix="/api/dm", tags=["Social DMs"])


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class SendReplyRequest(BaseModel):
    platform: str  # whatsapp | instagram | messenger | x
    contact_name: str
    message: str
    polish: bool = True  # Use LLM to refine the message before sending


class DraftReplyRequest(BaseModel):
    contact_name: str
    message: str
    context: str = ""  # Optional conversation context


class AutoReplyRequest(BaseModel):
    platform: str
    style: str = "polite"  # polite | casual | professional | friendly


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/platforms")
async def list_platforms() -> Dict[str, Any]:
    """List all supported social platforms."""
    platforms = social_reply_service.get_supported_platforms()
    return {"platforms": platforms}


@router.get("/unread/{platform}")
async def check_unread(platform: str) -> Dict[str, Any]:
    """
    Check for unread messages on a specific platform.
    Requires the user to be logged in via the Jarvis browser.
    """
    result = await social_reply_service.check_unread(platform)
    if "error" in result and "Unknown platform" in result.get("error", ""):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/unread")
async def check_all_unread() -> Dict[str, Any]:
    """
    Scan ALL platforms for unread messages.
    Returns a combined summary with per-platform breakdowns.
    """
    return await social_reply_service.check_all_platforms()


@router.post("/open-chat")
async def open_chat(platform: str, contact_name: str) -> Dict[str, Any]:
    """Open a specific contact's chat on the given platform."""
    return await social_reply_service.open_chat(platform, contact_name)


@router.post("/draft")
async def draft_reply(req: DraftReplyRequest) -> Dict[str, Any]:
    """
    Draft a polished reply using LLM without sending it.
    Returns the original and refined message for review.
    """
    result = await social_reply_service.draft_reply(
        contact_name=req.contact_name,
        message=req.message,
        context=req.context,
    )
    return result


@router.post("/send")
async def send_reply(req: SendReplyRequest) -> Dict[str, Any]:
    """
    Send a reply to a contact on a specific platform.
    Opens the chat, types the message, and sends it.
    If polish=true (default), the message is refined by LLM first.
    """
    result = await social_reply_service.send_reply(
        platform=req.platform,
        contact_name=req.contact_name,
        message=req.message,
        polish=req.polish,
    )
    return result


@router.get("/messages/{platform}/{contact_name}")
async def read_messages(platform: str, contact_name: str, count: int = 10) -> Dict[str, Any]:
    """
    Read the latest messages from a contact on a platform.
    Opens the chat and extracts visible message text.
    """
    return await social_reply_service.read_latest_messages(platform, contact_name, count)


@router.post("/auto-reply")
async def auto_reply(req: AutoReplyRequest) -> Dict[str, Any]:
    """
    Auto-reply to ALL unread messages on a platform.
    Uses LLM to generate contextual replies for each unread conversation.
    Styles: polite, casual, professional, friendly.
    """
    result = await social_reply_service.auto_reply_all(
        platform=req.platform,
        style=req.style,
    )
    return result
