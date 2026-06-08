# ====================================================================
# JARVIS OMEGA — SaaS Boilerplate Generator Router
# ====================================================================
"""
Boilerplate Generator REST API and WebSocket endpoints.
Provides endpoints for generation, live dev-servers, GitHub sync, Vercel deploys,
and real-time dev log streaming.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

import os
import json
import zipfile
import tempfile
from pathlib import Path
from fastapi.responses import FileResponse
from backend.config import settings

from backend.services.boilerplate_service import boilerplate_service
from shared.logger import get_logger

log = get_logger("router_build")
router = APIRouter(prefix="/api/build", tags=["SaaS Boilerplate Studio"])


class GenerateRequest(BaseModel):
    prompt: str


class DeployRequest(BaseModel):
    repo_name: str


class SaveFileRequest(BaseModel):
    filepath: str
    content: str


class PatchRequest(BaseModel):
    error_log: str


@router.post("/generate", response_model=Dict[str, Any])
async def generate_project(req: GenerateRequest):
    """Generate a new project boilerplate from prompt."""
    try:
        meta = await boilerplate_service.generate_project(req.prompt)
        return meta
    except Exception as e:
        log.error("boilerplate_generation_endpoint_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project generation failed: {str(e)}"
        )


@router.get("/{project_id}/files", response_model=Dict[str, Any])
async def get_project_files(project_id: str):
    """Retrieve file structure and content of a generated project."""
    try:
        files_data = await boilerplate_service.get_project_files(project_id)
        return files_data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        log.error("get_project_files_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{project_id}/file", response_model=Dict[str, Any])
async def save_project_file(project_id: str, req: SaveFileRequest):
    """Save code changes from Monaco editor to disk."""
    success = await boilerplate_service.save_project_file(project_id, req.filepath, req.content)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to save file. Check directory path.")
    return {"status": "success", "file": req.filepath}


@router.post("/{project_id}/run", response_model=Dict[str, Any])
async def run_local_dev(project_id: str):
    """Launch the local development server for the generated project."""
    result = await boilerplate_service.run_local_dev(project_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("message", "Dev server failed to start"))
    return result


@router.post("/{project_id}/deploy", response_model=Dict[str, Any])
async def deploy_project(project_id: str, req: DeployRequest):
    """Push code to GitHub and trigger Vercel deployment."""
    try:
        # 1. Push to GitHub
        github_url = await boilerplate_service.push_to_github(project_id, req.repo_name)
        
        # 2. Deploy to Vercel
        vercel_url = await boilerplate_service.deploy_to_vercel(project_id, github_url)
        
        return {
            "status": "deployed",
            "github_url": github_url,
            "vercel_url": vercel_url
        }
    except Exception as e:
        log.error("boilerplate_deploy_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/patch", response_model=Dict[str, Any])
async def patch_project(project_id: str, req: PatchRequest):
    """Attempt LLM auto-patching of build errors."""
    try:
        from backend.services.self_healing import self_healing
        result = await self_healing.auto_fix_and_redeploy(
            project_dir=f"./workspace/builds/{project_id}",
            errors=req.error_log,
            vercel_project_name=project_id
        )
        return result
    except Exception as e:
        log.error("boilerplate_patch_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/logs/{project_id}")
async def websocket_logs(websocket: WebSocket, project_id: str):
    """WebSocket endpoint for real-time local server logs streaming."""
    await websocket.accept()
    last_index = 0
    try:
        while True:
            logs = boilerplate_service.get_server_logs(project_id)
            if len(logs) > last_index:
                for line in logs[last_index:]:
                    await websocket.send_text(line)
                last_index = len(logs)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("websocket_logs_error", project_id=project_id, error=str(e))


@router.get("/{project_id}/download")
async def download_project(project_id: str):
    """Zips the generated project folder and returns it as a download file."""
    build_dir = Path(settings.workspace_dir) / "builds" / project_id
    if not build_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine project name
    meta_file = build_dir / ".jarvis_meta.json"
    project_name = project_id
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            project_name = meta.get("prompt", project_id)[:30]
            project_name = "".join(c for c in project_name if c.isalnum() or c in ("-", "_")).strip() or project_id
        except Exception:
            pass

    # Create temporary zip file
    temp_zip = Path(tempfile.gettempdir()) / f"{project_name}_{project_id}.zip"
    
    try:
        # Zip the directory excluding node_modules, .git, .next, dist, build
        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(build_dir):
                # Modify dirs in-place to exclude directories
                dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".next", "dist", "build")]
                for file in files:
                    # Don't include the metadata or temp files in user download if they are private
                    if file == ".jarvis_meta.json":
                        continue
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(build_dir)
                    zipf.write(file_path, rel_path)

        return FileResponse(
            path=str(temp_zip),
            media_type="application/x-zip-compressed",
            filename=f"{project_name}.zip"
        )
    except Exception as e:
        log.error("zip_project_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create download zip: {str(e)}")

