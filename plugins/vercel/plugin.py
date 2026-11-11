# ====================================================================
# JARVIS OMEGA — Vercel Plugin (read + write)
# ====================================================================
"""
Vercel tools: read (projects, deployments, domains) and write
(redeploy, cancel a deployment). All of them need an API token
connected with /connect vercel (stored encrypted in the vault under
``vercel_token``).

Read tools are TIER_0_OBSERVE. Write tools are TIER_4_EXTERNAL —
the approval gateway asks Sir before any of them runs, because each
one changes something outside Jarvis (a new deployment, a cancelled
deployment).
"""

from __future__ import annotations

from typing import Any

from backend.services import vercel_connector
from backend.tools import RiskTier, tool


@tool(
    name="vercel.list_projects",
    description="List Vercel projects.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 10}},
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="vercel",
)
async def vercel_list_projects(limit: int = 10) -> dict[str, Any]:
    return await vercel_connector.list_projects(limit)


@tool(
    name="vercel.list_deployments",
    description="List Vercel deployments, optionally for one project.",
    parameters={
        "type": "object",
        "properties": {
            "project": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 10},
        },
        "required": [],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="vercel",
)
async def vercel_list_deployments(
    project: str = "", limit: int = 10
) -> dict[str, Any]:
    return await vercel_connector.list_deployments(project, limit)


@tool(
    name="vercel.get_deployment",
    description="Get the state of one Vercel deployment by id.",
    parameters={
        "type": "object",
        "properties": {"deployment_id": {"type": "string"}},
        "required": ["deployment_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="vercel",
)
async def vercel_get_deployment(deployment_id: str) -> dict[str, Any]:
    return await vercel_connector.get_deployment(deployment_id)


@tool(
    name="vercel.list_domains",
    description="List the domains of a Vercel project.",
    parameters={
        "type": "object",
        "properties": {"project": {"type": "string"}},
        "required": ["project"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="vercel",
)
async def vercel_list_domains(project: str) -> dict[str, Any]:
    return await vercel_connector.list_domains(project)


@tool(
    name="vercel.redeploy",
    description="Redeploy a Vercel deployment: create a fresh deployment from an existing one.",
    parameters={
        "type": "object",
        "properties": {"deployment_id": {"type": "string"}},
        "required": ["deployment_id"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="vercel",
)
async def vercel_redeploy(deployment_id: str) -> dict[str, Any]:
    return await vercel_connector.redeploy(deployment_id)


@tool(
    name="vercel.cancel_deployment",
    description="Cancel a Vercel deployment that is still building.",
    parameters={
        "type": "object",
        "properties": {"deployment_id": {"type": "string"}},
        "required": ["deployment_id"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="vercel",
)
async def vercel_cancel_deployment(deployment_id: str) -> dict[str, Any]:
    return await vercel_connector.cancel_deployment(deployment_id)
