"""
Pattern Detection & Workflow Router.
Exposes pattern detection, workflow automation, and goal execution endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.services.pattern_detector import pattern_detector
from shared.logger import get_logger

log = get_logger("router_patterns")
router = APIRouter(prefix="/api/patterns", tags=["Patterns & Workflows"])


@router.get("/detect")
async def detect_patterns() -> Dict[str, Any]:
    """Scan execution history for repeated command patterns."""
    patterns = pattern_detector.detect_patterns()
    return {
        "patterns": patterns,
        "count": len(patterns),
        "total_commands": len(pattern_detector._history),
    }


@router.get("/stats")
async def get_pattern_stats() -> Dict[str, Any]:
    """Get pattern detection statistics."""
    return pattern_detector.get_stats()


@router.post("/workflows")
async def create_workflow(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new workflow from a list of commands."""
    name = data.get("name", "")
    commands = data.get("commands", [])
    description = data.get("description", "")
    cron = data.get("cron", "")
    if not commands:
        raise HTTPException(status_code=400, detail="commands list is required")
    if not name:
        name = pattern_detector.suggest_workflow_name({"command_types": ["other"]})
    workflow = pattern_detector.create_workflow(name, commands, description)
    if cron:
        workflow["cron"] = cron
        _schedule_workflow_cron(workflow, cron)
    return workflow


@router.get("/workflows")
async def list_workflows() -> Dict[str, Any]:
    """List all saved workflows."""
    workflows = pattern_detector.get_workflows()
    return {"workflows": workflows, "count": len(workflows)}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> Dict[str, Any]:
    """Get a specific workflow by ID."""
    workflows = pattern_detector.get_workflows()
    for wf in workflows:
        if wf["workflow_id"] == workflow_id:
            return wf
    raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update a workflow's name, description, commands, or cron schedule."""
    workflows = pattern_detector.get_workflows()
    target = None
    for wf in workflows:
        if wf["workflow_id"] == workflow_id:
            target = wf
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    if "name" in data:
        target["name"] = data["name"]
    if "description" in data:
        target["description"] = data["description"]
    if "commands" in data:
        if not data["commands"]:
            raise HTTPException(status_code=400, detail="commands list cannot be empty")
        target["commands"] = data["commands"]
        target["step_count"] = len(data["commands"])
    if "cron" in data:
        target["cron"] = data["cron"]
        _schedule_workflow_cron(target, data["cron"])

    target["updated_at"] = datetime.utcnow().isoformat()
    pattern_detector._save()
    return target


@router.post("/workflows/{workflow_id}/schedule")
async def schedule_workflow(workflow_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Schedule a workflow with a cron expression."""
    workflows = pattern_detector.get_workflows()
    target = None
    for wf in workflows:
        if wf["workflow_id"] == workflow_id:
            target = wf
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    cron = data.get("cron", "")
    if not cron:
        raise HTTPException(status_code=400, detail="cron expression is required")

    target["cron"] = cron
    target["updated_at"] = datetime.utcnow().isoformat()
    pattern_detector._save()

    job_id = _schedule_workflow_cron(target, cron)
    return {"status": "scheduled", "workflow_id": workflow_id, "cron": cron, "job_id": job_id}


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str) -> Dict[str, Any]:
    """Execute a workflow's commands sequentially."""
    result = pattern_detector.run_workflow(workflow_id)
    if not result.get("success") and "not found" in result.get("error", ""):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str) -> Dict[str, Any]:
    """Delete a workflow."""
    success = pattern_detector.delete_workflow(workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    _cancel_workflow_job(workflow_id)
    return {"status": "deleted", "workflow_id": workflow_id}


def _schedule_workflow_cron(workflow: Dict[str, Any], cron: str) -> str:
    """Schedule a workflow job in APScheduler."""
    from backend.scheduler import scheduler

    wf_id = workflow["workflow_id"]
    job_id = f"wf_{wf_id}"

    if hasattr(scheduler, 'cancel_job'):
        scheduler.cancel_job(job_id)

    scheduler.schedule_cron(
        job_id=job_id,
        func="run_workflow_by_id",
        args=[wf_id],
        cron_expression=cron,
        description=f"Workflow: {workflow.get('name', '')}"
    )
    return job_id


def _cancel_workflow_job(workflow_id: str):
    """Cancel a scheduled workflow job."""
    from backend.scheduler import scheduler
    job_id = f"wf_{workflow_id}"
    if hasattr(scheduler, 'cancel_job'):
        scheduler.cancel_job(job_id)


@router.post("/suggest")
async def suggest_workflow() -> Dict[str, Any]:
    """
    Automatically suggest a workflow based on detected patterns.
    Creates a workflow from the most frequent pattern.
    """
    patterns = pattern_detector.detect_patterns()
    if not patterns:
        return {"suggested": False, "message": "No patterns detected yet"}

    best = patterns[0]
    if best["frequency"] < 2:
        return {"suggested": False, "message": f"Pattern only seen {best['frequency']} time(s), need at least 2"}

    name = pattern_detector.suggest_workflow_name(best)
    workflow = pattern_detector.create_workflow(
        name=name,
        commands=best["commands"],
        description=f"Automated from pattern seen {best['frequency']} times",
    )
    return {"suggested": True, "pattern": best, "workflow": workflow}
