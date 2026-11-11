# ====================================================================
# JARVIS OMEGA — GitHub Connector (read + write)
# ====================================================================
"""
GitHub connector: read AND write via the REST API, token in the vault.

The token lives encrypted in the credentials vault under ``github_pat``
— the same key the github_free plugin already reads, so connecting
here also unlocks private repos in the existing read tools. A token
from the ``GITHUB_TOKEN`` env var is used as a fallback when the vault
is empty.

Sir connects with /connect github on Telegram: he pastes a
fine-grained or classic PAT, Jarvis verifies it with GET /user BEFORE
storing it, and the token is never logged or echoed back. /disconnect
github removes it — the only way the token leaves the vault.

Write operations (create issue / comment / PR / merge / commit a file /
trigger a workflow) are exposed as tools at TIER_4_EXTERNAL, so the
approval gateway asks Sir before any of them runs.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("github_connector")

_GH = "https://api.github.com"
VAULT_KEY = "github_pat"


def token() -> str | None:
    """The GitHub PAT: vault first, GITHUB_TOKEN env as fallback."""
    try:
        saved = credentials_vault.get(VAULT_KEY)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("github_token_vault_read_failed", error=str(e))
        saved = None
    if saved:
        return saved
    env = (os.environ.get("GITHUB_TOKEN") or "").strip()
    return env or None


def is_connected() -> bool:
    return token() is not None


def _headers(tok: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JARVIS-OMEGA/1.0",
        "Authorization": f"Bearer {tok}",
    }


def _public_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JARVIS-OMEGA/1.0",
    }


async def verify_token(
    tok: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Check a PAT with GET /user. Returns login + scopes, or None."""
    tok = (tok or "").strip()
    if not tok:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(f"{_GH}/user", headers=_headers(tok))
        if resp.status_code != 200:
            return None
        data = resp.json()
        scopes = resp.headers.get("x-oauth-scopes", "")
        return {
            "login": data.get("login"),
            "name": data.get("name"),
            "scopes": [s.strip() for s in scopes.split(",") if s.strip()],
            "rate_limit_remaining": resp.headers.get("x-ratelimit-remaining"),
        }
    except (httpx.HTTPError, ValueError) as e:
        log.warning("github_verify_failed", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


def save_token(tok: str) -> None:
    """Store a verified PAT encrypted in the vault."""
    credentials_vault.set(VAULT_KEY, (tok or "").strip(), category="connector")


def delete_token() -> bool:
    """Remove the PAT from the vault. Returns True when one was stored."""
    return credentials_vault.delete(VAULT_KEY)


async def status(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Connection state: connected, login, rate limit remaining."""
    tok = token()
    if not tok:
        return {"connected": False, "login": None, "rate_limit_remaining": None}
    info = await verify_token(tok, client=client)
    if info is None:
        return {"connected": False, "login": None, "rate_limit_remaining": None}
    return {
        "connected": True,
        "login": info.get("login"),
        "rate_limit_remaining": info.get("rate_limit_remaining"),
    }


async def _request(
    method: str,
    path: str,
    tok: str | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One GitHub API call. Returns {"ok", "status", "data"/"error"}."""
    tok = tok or token()
    headers = _headers(tok) if tok else _public_headers()
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.request(
            method, f"{_GH}{path}", headers=headers, json=json_body, params=params
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


def _require_token() -> str | None:
    return token()


# --------------------------------------------------------------------
# Read
# --------------------------------------------------------------------

async def list_repos(
    username: str, limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Repos of a user (or the token owner when username is 'me')."""
    if username.strip().lower() == "me":
        info = await verify_token(token() or "", client=client)
        username = (info or {}).get("login") or username
    result = await _request(
        "GET", f"/users/{username}/repos",
        params={"per_page": min(limit, 100), "sort": "updated"}, client=client,
    )
    if not result.get("ok"):
        return result
    repos = result["data"] or []
    return {
        "ok": True,
        "username": username,
        "count": len(repos[:limit]),
        "repos": [
            {
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "description": r.get("description"),
                "url": r.get("html_url"),
                "stars": r.get("stargazers_count"),
                "language": r.get("language"),
                "default_branch": r.get("default_branch"),
                "updated_at": r.get("updated_at"),
            }
            for r in repos[:limit]
        ],
    }


async def get_repo(
    owner: str, repo: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    result = await _request("GET", f"/repos/{owner}/{repo}", client=client)
    if not result.get("ok"):
        return result
    r = result["data"] or {}
    return {
        "ok": True,
        "full_name": r.get("full_name"),
        "description": r.get("description"),
        "url": r.get("html_url"),
        "stars": r.get("stargazers_count"),
        "forks": r.get("forks_count"),
        "open_issues": r.get("open_issues_count"),
        "default_branch": r.get("default_branch"),
        "updated_at": r.get("updated_at"),
    }


async def list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    result = await _request(
        "GET", f"/repos/{owner}/{repo}/issues",
        params={"state": state, "per_page": min(limit, 100)}, client=client,
    )
    if not result.get("ok"):
        return result
    issues = [i for i in (result["data"] or []) if "pull_request" not in i]
    return {
        "ok": True,
        "count": len(issues[:limit]),
        "issues": [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "url": i.get("html_url"),
                "author": (i.get("user") or {}).get("login"),
                "created_at": i.get("created_at"),
            }
            for i in issues[:limit]
        ],
    }


async def list_prs(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    result = await _request(
        "GET", f"/repos/{owner}/{repo}/pulls",
        params={"state": state, "per_page": min(limit, 100)}, client=client,
    )
    if not result.get("ok"):
        return result
    prs = result["data"] or []
    return {
        "ok": True,
        "count": len(prs[:limit]),
        "prs": [
            {
                "number": p.get("number"),
                "title": p.get("title"),
                "state": p.get("state"),
                "url": p.get("html_url"),
                "author": (p.get("user") or {}).get("login"),
                "created_at": p.get("created_at"),
            }
            for p in prs[:limit]
        ],
    }


async def list_commits(
    owner: str,
    repo: str,
    branch: str = "",
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": min(limit, 100)}
    if branch:
        params["sha"] = branch
    result = await _request(
        "GET", f"/repos/{owner}/{repo}/commits", params=params, client=client
    )
    if not result.get("ok"):
        return result
    commits = result["data"] or []
    return {
        "ok": True,
        "count": len(commits[:limit]),
        "commits": [
            {
                "sha": (c.get("sha") or "")[:7],
                "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0],
                "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                "url": c.get("html_url"),
            }
            for c in commits[:limit]
        ],
    }


# --------------------------------------------------------------------
# Write — every one of these needs the PAT; the tools gate them at
# TIER_4_EXTERNAL so Sir approves before any of them runs.
# --------------------------------------------------------------------

async def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "GitHub is not connected — /connect github first."}
    result = await _request(
        "POST", f"/repos/{owner}/{repo}/issues", tok=tok,
        json_body={"title": title, "body": body}, client=client,
    )
    if not result.get("ok"):
        return result
    issue = result["data"] or {}
    return {"ok": True, "number": issue.get("number"), "url": issue.get("html_url")}


async def comment_issue(
    owner: str,
    repo: str,
    number: int,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "GitHub is not connected — /connect github first."}
    result = await _request(
        "POST", f"/repos/{owner}/{repo}/issues/{number}/comments", tok=tok,
        json_body={"body": body}, client=client,
    )
    if not result.get("ok"):
        return result
    comment = result["data"] or {}
    return {"ok": True, "id": comment.get("id"), "url": comment.get("html_url")}


async def create_pr(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "GitHub is not connected — /connect github first."}
    result = await _request(
        "POST", f"/repos/{owner}/{repo}/pulls", tok=tok,
        json_body={"title": title, "head": head, "base": base, "body": body},
        client=client,
    )
    if not result.get("ok"):
        return result
    pr = result["data"] or {}
    return {"ok": True, "number": pr.get("number"), "url": pr.get("html_url")}


async def merge_pr(
    owner: str,
    repo: str,
    number: int,
    merge_method: str = "merge",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "GitHub is not connected — /connect github first."}
    result = await _request(
        "PUT", f"/repos/{owner}/{repo}/pulls/{number}/merge", tok=tok,
        json_body={"merge_method": merge_method}, client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    return {"ok": True, "merged": data.get("merged"), "message": data.get("message")}


async def create_or_update_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Commit a file: creates it, or updates it when it already exists."""
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "GitHub is not connected — /connect github first."}
    # An update needs the current blob SHA; a 404 means it is a create.
    sha: str | None = None
    existing = await _request(
        "GET", f"/repos/{owner}/{repo}/contents/{path}",
        tok=tok, params={"ref": branch} if branch else None, client=client,
    )
    if existing.get("ok"):
        sha = (existing["data"] or {}).get("sha")
    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if branch:
        body["branch"] = branch
    if sha:
        body["sha"] = sha
    result = await _request(
        "PUT", f"/repos/{owner}/{repo}/contents/{path}", tok=tok,
        json_body=body, client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    commit = data.get("commit") or {}
    return {
        "ok": True,
        "sha": (commit.get("sha") or "")[:7],
        "url": (data.get("content") or {}).get("html_url"),
    }


async def trigger_workflow(
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str = "main",
    inputs: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "GitHub is not connected — /connect github first."}
    body: dict[str, Any] = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    result = await _request(
        "POST",
        f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
        tok=tok, json_body=body, client=client,
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "dispatched": True, "workflow": workflow_id, "ref": ref}
