from __future__ import annotations

import logging
from fastapi import APIRouter
from typing import Any

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/finance", tags=["Finance"])


@router.get("/arbitrage")
async def get_arbitrage_opportunities() -> dict[str, Any]:
    return {"opportunities": [], "message": "Market data service not configured. Set up API keys for real-time data."}


@router.get("/markets")
async def get_market_overview() -> dict[str, Any]:
    return {"markets": [], "message": "Market overview service not configured."}
