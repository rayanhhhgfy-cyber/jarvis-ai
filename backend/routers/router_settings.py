# ====================================================================
# JARVIS OMEGA — Settings Router
# ====================================================================
"""
REST endpoints for managing plugin credentials via the credentials vault.

The vault NEVER returns plaintext over the API — only masked previews. Writes
accept plaintext from Sir (over HTTPS / localhost) and persist encrypted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("router_settings")
router = APIRouter(prefix="/api/settings", tags=["Settings"])


# --------------------------------------------------------------------
# Models
# --------------------------------------------------------------------

class CredentialSetRequest(BaseModel):
    key: str = Field(..., description="Vault key, e.g. 'openrouter_api_key'.")
    value: str = Field(..., description="Plaintext value to encrypt and store.")
    category: str = Field("general", description="Free-form label for grouping.")


class CredentialSetResponse(BaseModel):
    key: str
    stored: bool
    masked_preview: str


# --------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------

@router.get("/credentials")
async def list_credentials() -> List[Dict[str, Any]]:
    """List every credential in the vault — masked, never plaintext."""
    return credentials_vault.list_keys()


@router.get("/credentials/{key}")
async def get_credential_metadata(key: str) -> Dict[str, Any]:
    """Return metadata (including masked preview) for a single credential."""
    if not credentials_vault.has(key):
        raise HTTPException(status_code=404, detail=f"Credential '{key}' not found")
    return {
        "key": key,
        "category": credentials_vault._entries.get(key, {}).get("category", "general"),
        "masked_preview": credentials_vault._mask(key),
    }


@router.put("/credentials", response_model=CredentialSetResponse)
async def set_credential(req: CredentialSetRequest) -> CredentialSetResponse:
    """Insert or replace a credential."""
    try:
        credentials_vault.set(req.key, req.value, category=req.category)
        log.info("credential_set", key=req.key, category=req.category)
        return CredentialSetResponse(
            key=req.key,
            stored=True,
            masked_preview=credentials_vault._mask(req.key),
        )
    except Exception as e:
        log.error("credential_set_failed", key=req.key, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to store credential: {e}")


@router.delete("/credentials/{key}")
async def delete_credential(key: str):
    """Remove a credential from the vault."""
    if not credentials_vault.delete(key):
        raise HTTPException(status_code=404, detail=f"Credential '{key}' not found")
    return {"deleted": True, "key": key}


# --------------------------------------------------------------------
# Tool registry introspection
# --------------------------------------------------------------------

@router.get("/tools")
async def list_tools() -> List[Dict[str, Any]]:
    """Return metadata for every tool currently registered."""
    from backend.tools import get_registry
    return [
        {
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "risk_tier": t.risk_tier.value,
            "enabled": t.enabled,
            "requires_approval": t.requires_approval,
        }
        for t in get_registry().all_tools()
    ]


# --------------------------------------------------------------------
# Phase 9 — Self-Healing & Self-Modification
# --------------------------------------------------------------------

class SelfModifyFixRequest(BaseModel):
    traceback: str = Field(..., description="The traceback / error message to diagnose and fix.")
    apply: bool = Field(True, description="If False, only propose a patch; do not write files.")


class SelfModifyAddCapRequest(BaseModel):
    request: str = Field(..., description="Natural-language description of the desired capability.")


@router.post("/self_heal/fix")
async def trigger_self_fix(req: SelfModifyFixRequest):
    """
    Manually trigger the self-healing pipeline against a traceback.

    The pipeline respects the same guardrails as the automatic path:
    protected paths are never edited, every edit is backed up, and pytest
    must pass after the patch.
    """
    from backend.self_heal import try_heal
    from backend.config import settings as cfg
    record = await try_heal(
        traceback_str=req.traceback,
        context={"source": "manual", "endpoint": "/api/settings/self_heal/fix"},
        requesting_agent="sir",
    )
    # ``apply`` overrides allow_self_modification only when more permissive;
    # it cannot enable edits that the global setting disallows.
    if not req.apply:
        record = {**record, "note": "apply=False — patch proposed but not written"}
    return record


@router.post("/self_heal/add_capability")
async def trigger_add_capability(req: SelfModifyAddCapRequest):
    """
    Ask JARVIS to write a new plugin implementing a capability it doesn't have.
    """
    from shared.constants import AgentType, TaskStatus
    from shared.models import TaskDefinition
    from local_client.agents.agent_self_modify import AgentSelfModify

    task = TaskDefinition(
        title="add_capability",
        description=f"Sir requested: {req.request}",
        agent_type=AgentType.SELF_MODIFY,
        payload={
            "action": "add_capability",
            "request": req.request,
            "allow_self_modification": True,  # explicit override from Sir
        },
    )
    result = await AgentSelfModify().execute_task(task)
    return result.model_dump(mode="json")


@router.get("/self_heal/audit")
async def list_self_heal_audit(limit: int = 50):
    """List the most recent self-heal / self-modification attempts."""
    audit_dir = Path("./storage/self_modify_audit")
    if not audit_dir.exists():
        return []
    entries = []
    for p in sorted(audit_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            entries.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return entries


# --------------------------------------------------------------------
# Phase 15: Direct tool invocation endpoint
# --------------------------------------------------------------------

class ToolInvokeRequest(BaseModel):
    name: str = Field(..., description="Tool name, e.g. 'diagnostics.full'.")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments dict.")
    session_id: str = Field("default", description="Session for approval memory.")


@router.post("/tools/invoke")
async def invoke_tool(req: ToolInvokeRequest):
    """
    Directly invoke a registered tool by name with the given arguments.
    Bypasses the chat router + LLM — useful for testing and automation.
    """
    from backend.tools.executor import tool_executor
    result = await tool_executor.invoke(
        name=req.name,
        arguments=req.arguments,
        session_id=req.session_id,
    )
    return result
