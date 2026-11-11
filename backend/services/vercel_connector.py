# ====================================================================
# JARVIS OMEGA — Vercel Connector (read + write)
# ====================================================================
"""
Vercel connector: read AND write via the REST API, token in the vault.

The token lives encrypted in the credentials vault under
``vercel_token``. A token from the ``VERCEL_TOKEN`` env var is used
as a fallback when the vault is empty; ``VERCEL_TEAM_ID`` (env) scopes
calls to Sir's team when set.

Sir connects with /connect vercel on Telegram: he pastes a Vercel
API token (Account Settings → Tokens), Jarvis verifies it with
GET /v2/user BEFORE storing it, and the token is never logged or
echoed back. /disconnect vercel removes it — the only way the token
leaves the vault.

Write operations (redeploy, cancel a deployment) are exposed as tools
at TIER_4_EXTERNAL, so the approval gateway asks Sir before any of
them runs.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("vercel_connector")

_VC = "https://api.vercel.com"
VAULT_KEY = "vercel_token"


def token() -> str | None:
    """The Vercel API token: vault first, VERCEL_TOKEN env as fallback."""
    try:
        saved = credentials_vault.get(VAULT_KEY)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("vercel_token_vault_read_failed", error=str(e))
        saved = None
    if saved:
        return saved
    env = (os.environ.get("VERCEL_TOKEN") or "").strip()
    return env or None


def team_id() -> str | None:
    team = (os.environ.get("VERCEL_TEAM_ID") or "").strip()
    return team or None


def is_connected() -> bool:
    return token() is not None


def _headers(tok: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }


async def verify_token(
    tok: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Check a token with GET /v2/user. Returns user info, or None."""
    tok = (tok or "").strip()
    if not tok:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(f"{_VC}/v2/user", headers=_headers(tok))
        if resp.status_code != 200:
            return None
        data = (resp.json() or {}).get("user") or {}
        return {
            "id": data.get("id"),
            "username": data.get("username"),
            "email": data.get("email"),
            "name": data.get("name"),
        }
    except (httpx.HTTPError, ValueError) as e:
        log.warning("vercel_verify_failed", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


def save_token(tok: str) -> None:
    """Store a verified token encrypted in the vault."""
    credentials_vault.set(VAULT_KEY, (tok or "").strip(), category="connector")


def delete_token() -> bool:
    """Remove the token from the vault. Returns True when one was stored."""
    return credentials_vault.delete(VAULT_KEY)


async def status(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Connection state: connected, username, team."""
    tok = token()
    if not tok:
        return {"connected": False, "username": None, "team": team_id()}
    info = await verify_token(tok, client=client)
    if info is None:
        return {"connected": False, "username": None, "team": team_id()}
    return {"connected": True, "username": info.get("username"), "team": team_id()}


async def _request(
    method: str,
    path: str,
    tok: str | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One Vercel API call. Returns {"ok", "status", "data"/"error"}."""
    tok = tok or token()
    if not tok:
        return {"ok": False, "status": 0, "error": "Vercel is not connected."}
    params = dict(params or {})
    team = team_id()
    if team:
        params.setdefault("teamId", team)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.request(
            method, f"{_VC}{path}", headers=_headers(tok),
            json=json_body, params=params,
        )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        if resp.status_code == 204:
            return {"ok": True, "status": 204, "data": {}}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "status": 0, "error": str(e)[:300]}
    finally:
        if own_client:
            await client.aclose()


# --------------------------------------------------------------------
# Read
# --------------------------------------------------------------------

async def list_projects(
    limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    result = await _request(
        "GET", "/v9/projects", params={"limit": min(limit, 100)}, client=client
    )
    if not result.get("ok"):
        return result
    projects = (result["data"] or {}).get("projects") or []
    return {
        "ok": True,
        "count": len(projects[:limit]),
        "projects": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "framework": p.get("framework"),
                "updated_at": p.get("updatedAt"),
            }
            for p in projects[:limit]
        ],
    }


async def list_deployments(
    project: str = "",
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if project:
        params["projectId"] = project
    result = await _request(
        "GET", "/v6/deployments", params=params, client=client
    )
    if not result.get("ok"):
        return result
    deployments = (result["data"] or {}).get("deployments") or []
    return {
        "ok": True,
        "count": len(deployments[:limit]),
        "deployments": [
            {
                "id": d.get("uid"),
                "name": d.get("name"),
                "url": d.get("url"),
                "state": d.get("state"),
                "created_at": d.get("createdAt"),
            }
            for d in deployments[:limit]
        ],
    }


async def get_deployment(
    deployment_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    result = await _request(
        "GET", f"/v13/deployments/{deployment_id}", client=client
    )
    if not result.get("ok"):
        return result
    d = result["data"] or {}
    return {
        "ok": True,
        "id": d.get("uid"),
        "name": d.get("name"),
        "url": d.get("url"),
        "state": d.get("state"),
        "ready_state": d.get("readyState"),
        "created_at": d.get("createdAt"),
    }


async def list_domains(
    project: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    result = await _request(
        "GET", f"/v9/projects/{project}/domains", client=client
    )
    if not result.get("ok"):
        return result
    domains = (result["data"] or {}).get("domains") or []
    return {
        "ok": True,
        "count": len(domains),
        "domains": [d.get("name") for d in domains],
    }


# --------------------------------------------------------------------
# Write — every one of these needs the token; the tools gate them at
# TIER_4_EXTERNAL so Sir approves before any of them runs.
# --------------------------------------------------------------------

async def redeploy(
    deployment_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Create a fresh deployment from an existing one (a redeploy)."""
    tok = token()
    if not tok:
        return {"ok": False, "error": "Vercel is not connected — /connect vercel first."}
    current = await get_deployment(deployment_id, client=client)
    if not current.get("ok"):
        return current
    result = await _request(
        "POST", "/v13/deployments", tok=tok,
        json_body={"deploymentId": deployment_id, "name": current.get("name")},
        client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    return {
        "ok": True,
        "id": data.get("id"),
        "url": data.get("url"),
        "state": data.get("readyState") or data.get("state"),
    }


async def cancel_deployment(
    deployment_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    tok = token()
    if not tok:
        return {"ok": False, "error": "Vercel is not connected — /connect vercel first."}
    result = await _request(
        "DELETE", f"/v12/deployments/{deployment_id}", tok=tok, client=client
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "cancelled": True, "id": deployment_id}
