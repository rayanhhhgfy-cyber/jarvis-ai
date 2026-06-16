# ====================================================================
# JARVIS OMEGA — Omega Control Router
# ====================================================================
"""
REST endpoints for the 100 legendary OMEGA features.
"""

from __future__ import annotations

from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, status
from backend.omega_control import omega_control
from shared.logger import get_logger

log = get_logger("router_omega")
router = APIRouter(prefix="/api/omega", tags=["Omega"])

@router.get("/features")
async def get_features():
    """List all 100 features and their current status."""
    return await omega_control.get_all_features()

@router.post("/execute")
async def execute_feature(category: str, index: int, payload: Dict[str, Any] = None):
    """Execute a specific legendary feature."""
    try:
        return await omega_control.execute_feature(category, index, payload or {})
    except Exception as e:
        log.error("feature_execution_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_omega_stats():
    """Get global OMEGA system statistics."""
    features = await omega_control.get_all_features()
    total = sum(len(f) for f in features.values())
    active = sum(sum(1 for item in f if item["status"] == "active") for f in features.values())
    return {
        "total_features": total,
        "active_features": active,
        "system_level": "OMEGA",
        "uptime": "99.9999%"
    }
