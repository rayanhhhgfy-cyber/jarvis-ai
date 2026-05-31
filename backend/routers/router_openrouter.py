# ====================================================================
# JARVIS OMEGA — OpenRouter Proxy Router
# ====================================================================
"""
Proxy endpoints for direct OpenRouter queries, model listings,
and token/API key status checks.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.config import settings
from shared.logger import get_logger

log = get_logger("router_openrouter")
router = APIRouter(prefix="/api/openrouter", tags=["OpenRouter"])


@router.get("/status")
async def get_openrouter_status():
    """Verify configuration status of OpenRouter API integrations."""
    has_key = bool(settings.openrouter_api_key)
    return {
        "configured": has_key,
        "mythomax_model": settings.mythomax_model,
        "qwen_vision_model": settings.qwen_vision_model,
    }


@router.get("/models")
async def get_openrouter_models():
    """Lists the preferred model topologies configured for JARVIS OMEGA."""
    return [
        {
            "id": settings.mythomax_model,
            "name": "MythoMax L2 13B (Reasoning Core)",
            "context_length": 4096,
            "provider": "OpenRouter",
        },
        {
            "id": settings.qwen_vision_model,
            "name": "Qwen 2.5 VL 72B (Vision Core)",
            "context_length": 32768,
            "provider": "OpenRouter",
        }
    ]
