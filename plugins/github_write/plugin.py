# ====================================================================
# JARVIS OMEGA — GitHub Write Plugin (write operations, PAT required)
# ====================================================================
"""
Write tools for GitHub. Read tools already exist in github_free;
these are the writes, and they need a PAT connected with
/connect github (stored encrypted in the vault under ``github_pat``).

Every tool here is TIER_4_EXTERNAL — the approval gateway asks Sir
before any of them runs, because each one changes something outside
Jarvis (an issue, a comment, a PR, a merge, a commit, a workflow run).
"""

from __future__ import annotations

from typing import Any

from backend.services import github_connector
from backend.tools import RiskTier, tool


@tool(
    name="github.create_issue",
    description="Create an issue in a GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string", "default": ""},
        },
        "required": ["owner", "repo", "title"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="github_write",
)
async def github_create_issue(
    owner: str, repo: str, title: str, body: str = ""
) -> dict[str, Any]:
    return await github_connector.create_issue(owner, repo, title, body)


@tool(
    name="github.comment_issue",
    description="Post a comment on a GitHub issue or pull request.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "number": {"type": "integer"},
            "body": {"type": "string"},
        },
        "required": ["owner", "repo", "number", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="github_write",
)
async def github_comment_issue(
    owner: str, repo: str, number: int, body: str
) -> dict[str, Any]:
    return await github_connector.comment_issue(owner, repo, number, body)


@tool(
    name="github.create_pr",
    description="Open a pull request in a GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "title": {"type": "string"},
            "head": {"type": "string"},
            "base": {"type": "string"},
            "body": {"type": "string", "default": ""},
        },
        "required": ["owner", "repo", "title", "head", "base"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="github_write",
)
async def github_create_pr(
    owner: str, repo: str, title: str, head: str, base: str, body: str = ""
) -> dict[str, Any]:
    return await github_connector.create_pr(owner, repo, title, head, base, body)


@tool(
    name="github.merge_pr",
    description="Merge a pull request in a GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "number": {"type": "integer"},
            "merge_method": {
                "type": "string",
                "enum": ["merge", "squash", "rebase"],
                "default": "merge",
            },
        },
        "required": ["owner", "repo", "number"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="github_write",
)
async def github_merge_pr(
    owner: str, repo: str, number: int, merge_method: str = "merge"
) -> dict[str, Any]:
    return await github_connector.merge_pr(owner, repo, number, merge_method)


@tool(
    name="github.create_or_update_file",
    description="Commit a file to a GitHub repository (creates it, or updates it when it already exists).",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "message": {"type": "string"},
            "branch": {"type": "string", "default": ""},
        },
        "required": ["owner", "repo", "path", "content", "message"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="github_write",
)
async def github_create_or_update_file(
    owner: str, repo: str, path: str, content: str, message: str, branch: str = ""
) -> dict[str, Any]:
    return await github_connector.create_or_update_file(
        owner, repo, path, content, message, branch
    )


@tool(
    name="github.trigger_workflow",
    description="Trigger a GitHub Actions workflow run (workflow_dispatch).",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "workflow_id": {"type": "string"},
            "ref": {"type": "string", "default": "main"},
            "inputs": {"type": "object", "default": {}},
        },
        "required": ["owner", "repo", "workflow_id"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="github_write",
)
async def github_trigger_workflow(
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str = "main",
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await github_connector.trigger_workflow(owner, repo, workflow_id, ref, inputs)
