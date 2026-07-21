# ====================================================================
# JARVIS OMEGA — Groq Proxy Router
# ====================================================================
"""
Proxy endpoints for Groq Cloud service verification, Whisper model listing,
and key configuration checks.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.config import settings
from shared.logger import get_logger

log = get_logger("router_groq")
router = APIRouter(prefix="/api/groq", tags=["Groq"])


@router.get("/status")
async def get_groq_status():
    """Verify setup status of Groq Cloud API integrations."""
    has_key = bool(settings.groq_api_key)
    return {
        "configured": has_key,
        "whisper_model": settings.whisper_model,
    }


@router.get("/models")
async def get_groq_models():
    """Lists the preferred Groq audio model topology."""
    return [
        {
            "id": settings.whisper_model,
            "name": "Whisper Large V3 Turbo (STT Core)",
            "provider": "Groq",
        }
    ]
