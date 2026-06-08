# ====================================================================
# JARVIS OMEGA — Universal Smart Modder Router
# ====================================================================
"""
FastAPI router for mod management, including scanning games,
installing mods, and uninstalling mods.
"""

from __future__ import annotations

from typing import Any, Dict, List
from pydantic import BaseModel, HttpUrl

from fastapi import APIRouter, HTTPException, status

from backend.services.mod_manager_service import mod_manager_service
from shared.logger import get_logger

log = get_logger("router_mods")
router = APIRouter(prefix="/api/mods", tags=["Smart Modder"])


class InstallModRequest(BaseModel):
    game_id: str
    url: str


class UninstallModRequest(BaseModel):
    game_id: str
    mod_name: str


class ConfigDirRequest(BaseModel):
    game_id: str
    path: str


@router.get("/games", response_model=List[Dict[str, Any]])
async def list_games():
    """List detected games and installed mods."""
    try:
        return mod_manager_service.scan_installed_games()
    except Exception as e:
        log.error("list_games_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scan games: {str(e)}"
        )


@router.post("/install", response_model=Dict[str, Any])
async def install_mod(req: InstallModRequest):
    """Download and install a mod from a URL for a game."""
    try:
        result = await mod_manager_service.install_mod(req.game_id, req.url)
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Mod installation failed")
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("mod_install_endpoint_failed", game_id=req.game_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mod installation failed: {str(e)}"
        )


@router.post("/uninstall", response_model=Dict[str, Any])
async def uninstall_mod(req: UninstallModRequest):
    """Uninstall a mod by removing its files."""
    try:
        result = await mod_manager_service.uninstall_mod(req.game_id, req.mod_name)
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Mod uninstallation failed")
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("mod_uninstall_endpoint_failed", game_id=req.game_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mod uninstallation failed: {str(e)}"
        )


@router.post("/config-dir", response_model=Dict[str, Any])
async def config_game_dir(req: ConfigDirRequest):
    """Override the installation directory for a game."""
    try:
        mod_manager_service.set_game_dir(req.game_id, req.path)
        return {"success": True, "message": f"Updated install path for {req.game_id} to '{req.path}'."}
    except Exception as e:
        log.error("config_game_dir_failed", game_id=req.game_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update path: {str(e)}"
        )
