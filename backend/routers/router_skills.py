"""
Skill Management Router.
REST endpoints for uploading, listing, executing, and deleting skills.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from backend.services.skill_manager import skill_manager
from shared.logger import get_logger

log = get_logger("router_skills")
router = APIRouter(prefix="/api/skills", tags=["Skills"])


class InstallSkillRequest(BaseModel):
    name: str
    code: str


class ExecuteSkillRequest(BaseModel):
    params: Dict[str, Any] = {}


@router.get("")
async def list_skills() -> Dict[str, Any]:
    """List all installed skills."""
    skills = skill_manager.list_skills()
    return {"skills": skills, "count": len(skills)}


@router.get("/template")
async def get_skill_template() -> Dict[str, Any]:
    """Get a template for creating new skills."""
    return {"template": skill_manager.get_skill_template()}


@router.post("/install")
async def install_skill(req: InstallSkillRequest) -> Dict[str, Any]:
    """Install a new skill from Python source code."""
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Skill name is required")
    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="Skill code is required")

    result = await skill_manager.install_skill(req.name.strip(), req.code)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to install skill"))
    return result


@router.post("/upload")
async def upload_skill(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a skill Python file."""
    if not file.filename or not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="File must be a .py Python file")

    code = (await file.read()).decode("utf-8")
    name = file.filename.replace(".py", "")
    result = await skill_manager.install_skill(name, code)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to install skill"))
    return result


@router.get("/{name}")
async def get_skill(name: str) -> Dict[str, Any]:
    """Get skill details by name."""
    skill = skill_manager.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return skill


@router.post("/{name}/execute")
async def execute_skill(name: str, req: ExecuteSkillRequest = ExecuteSkillRequest()) -> Dict[str, Any]:
    """Execute a skill by name."""
    result = await skill_manager.execute_skill(name, req.params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Skill execution failed"))
    return result


@router.delete("/{name}")
async def delete_skill(name: str) -> Dict[str, Any]:
    """Delete an installed skill."""
    success = skill_manager.delete_skill(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {"status": "deleted", "name": name}
