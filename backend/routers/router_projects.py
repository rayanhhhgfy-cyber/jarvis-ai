# ====================================================================
# JARVIS OMEGA — Projects & Codebase Router
# ====================================================================
"""
REST endpoints for indexing, scanning dependencies, and querying the codebase
topological project knowledge graph.
"""

from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, status

from shared.models import ProjectInfo
from backend.project_scanner import project_scanner
from backend.project_graph import project_graph
from shared.logger import get_logger

log = get_logger("router_projects")
router = APIRouter(prefix="/api/projects", tags=["Projects"])


@router.post("/scan", response_model=ProjectInfo)
async def trigger_project_scan(path: Optional[str] = Query(None, description="Custom workspace path to scan")):
    """Scan and index the workspace files to refresh the dependency knowledge graph."""
    try:
        scanner = project_scanner
        if path:
            from backend.project_scanner import ProjectScanner
            scanner = ProjectScanner(workspace_path=path)
        info = await scanner.scan()
        return info
    except Exception as e:
        log.error("project_scan_trigger_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scan project: {str(e)}",
        )


@router.get("/graph", response_model=Optional[ProjectInfo])
async def get_project_graph():
    """Retrieve the current codebase structural topology metadata."""
    info = project_graph.get_project_info()
    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project graph has not been scanned yet. Trigger /api/projects/scan first.",
        )
    return info


@router.get("/dependencies", response_model=List[str])
async def get_project_dependencies():
    """Retrieve list of third-party package dependencies detected in code imports."""
    info = project_graph.get_project_info()
    if not info:
        return []
    return info.dependencies
