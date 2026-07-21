# ====================================================================
# JARVIS OMEGA - Free GitHub Plugin (public repos, no PAT required)
# ====================================================================
"""
Phase 10 plugin: GitHub REST API for public repositories. No personal
access token required for read operations on public repos.

  * ``github.list_repos``    - list a user's public repositories
  * ``github.read_file``     - read a file from a public repo
  * ``github.list_issues``   - list issues in a public repo
  * ``github.list_prs``      - list pull requests
  * ``github.list_commits``  - list recent commits
  * ``github.search_repos``  - search repositories by keyword
  * ``github.user``          - get info about a user

If a ``github_pat`` is present in the credentials vault, the plugin uses
it (raising rate limits + unlocking private repos you have access to).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_GH = "https://api.github.com"


def _headers() -> Dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JARVIS-OMEGA/1.0",
    }
    try:
        from backend.services.credentials_vault import credentials_vault
        pat = credentials_vault.get("github_pat")
        if pat:
            h["Authorization"] = f"Bearer {pat}"
    except Exception:
        pass
    return h


@tool(
    name="github.list_repos",
    description="List public repositories for a GitHub user.",
    parameters={
        "type": "object",
        "properties": {
            "username": {"type": "string"},
            "limit": {"type": "integer", "default": 30},
            "sort": {"type": "string", "enum": ["updated", "created", "pushed", "full_name"], "default": "updated"},
        },
        "required": ["username"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_list_repos(username: str, limit: int = 30, sort: str = "updated") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_GH}/users/{username}/repos",
                params={"per_page": min(limit, 100), "sort": sort},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        repos = resp.json()
        out = [
            {
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "description": r.get("description"),
                "url": r.get("html_url"),
                "stars": r.get("stargazers_count"),
                "forks": r.get("forks_count"),
                "language": r.get("language"),
                "default_branch": r.get("default_branch"),
                "updated_at": r.get("updated_at"),
            }
            for r in repos[:limit]
        ]
        return {"ok": True, "username": username, "count": len(out), "repos": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="github.read_file",
    description="Read a file from a public GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "path": {"type": "string", "description": "File path within the repo."},
            "branch": {"type": "string", "default": "", "description": "Defaults to the repo's default branch."},
            "max_chars": {"type": "integer", "default": 20000},
        },
        "required": ["owner", "repo", "path"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_read_file(owner: str, repo: str, path: str, branch: str = "", max_chars: int = 20000) -> Dict[str, Any]:
    try:
        url = f"{_GH}/repos/{owner}/{repo}/contents/{path}"
        params = {}
        if branch:
            params["ref"] = branch
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=_headers())
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        if isinstance(data, dict) and data.get("encoding") == "base64":
            import base64
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            return {
                "ok": True,
                "owner": owner, "repo": repo, "path": path,
                "size": data.get("size"),
                "sha": data.get("sha"),
                "content": content[:max_chars],
                "truncated": len(content) > max_chars,
            }
        return {"ok": False, "error": "file is a directory or unsupported encoding", "raw": str(data)[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="github.list_issues",
    description="List open issues in a public GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["owner", "repo"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_list_issues(owner: str, repo: str, state: str = "open", limit: int = 20) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_GH}/repos/{owner}/{repo}/issues",
                params={"state": state, "per_page": min(limit, 100)},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        issues = resp.json()
        out = [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "user": i.get("user", {}).get("login"),
                "url": i.get("html_url"),
                "created_at": i.get("created_at"),
                "labels": [l.get("name") for l in i.get("labels", [])],
                # Skip PRs (GitHub's issues endpoint returns them too).
            }
            for i in issues[:limit]
            if "pull_request" not in i
        ]
        return {"ok": True, "owner": owner, "repo": repo, "count": len(out), "issues": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="github.list_prs",
    description="List pull requests in a public GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["owner", "repo"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_list_prs(owner: str, repo: str, state: str = "open", limit: int = 20) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_GH}/repos/{owner}/{repo}/pulls",
                params={"state": state, "per_page": min(limit, 100)},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        prs = resp.json()
        out = [
            {
                "number": p.get("number"),
                "title": p.get("title"),
                "state": p.get("state"),
                "user": p.get("user", {}).get("login"),
                "url": p.get("html_url"),
                "head": p.get("head", {}).get("ref"),
                "base": p.get("base", {}).get("ref"),
                "draft": p.get("draft"),
                "merged": p.get("merged"),
            }
            for p in prs[:limit]
        ]
        return {"ok": True, "owner": owner, "repo": repo, "count": len(out), "pulls": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="github.list_commits",
    description="List recent commits in a public GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "branch": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["owner", "repo"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_list_commits(owner: str, repo: str, branch: str = "", limit: int = 10) -> Dict[str, Any]:
    try:
        params = {"per_page": min(limit, 100)}
        if branch:
            params["sha"] = branch
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_GH}/repos/{owner}/{repo}/commits",
                params=params, headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        commits = resp.json()
        out = [
            {
                "sha": c.get("sha"),
                "message": (c.get("commit", {}).get("message") or "").split("\n")[0],
                "author": c.get("commit", {}).get("author", {}).get("name"),
                "date": c.get("commit", {}).get("author", {}).get("date"),
                "url": c.get("html_url"),
            }
            for c in commits[:limit]
        ]
        return {"ok": True, "owner": owner, "repo": repo, "count": len(out), "commits": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="github.search_repos",
    description="Search public GitHub repositories by keyword.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "language": {"type": "string", "default": "", "description": "Optional language filter."},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_search_repos(query: str, language: str = "", limit: int = 10) -> Dict[str, Any]:
    q = query
    if language:
        q += f" language:{language}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_GH}/search/repositories",
                params={"q": q, "per_page": min(limit, 100), "sort": "stars"},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        items = resp.json().get("items", [])
        out = [
            {
                "full_name": i.get("full_name"),
                "description": i.get("description"),
                "url": i.get("html_url"),
                "stars": i.get("stargazers_count"),
                "language": i.get("language"),
                "topics": i.get("topics", []),
            }
            for i in items[:limit]
        ]
        return {"ok": True, "query": q, "count": len(out), "repos": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="github.user",
    description="Get info about a GitHub user.",
    parameters={
        "type": "object",
        "properties": {"username": {"type": "string"}},
        "required": ["username"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="github",
)
async def github_user(username: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_GH}/users/{username}", headers=_headers())
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        u = resp.json()
        return {
            "ok": True,
            "username": u.get("login"),
            "name": u.get("name"),
            "bio": u.get("bio"),
            "company": u.get("company"),
            "location": u.get("location"),
            "public_repos": u.get("public_repos"),
            "followers": u.get("followers"),
            "following": u.get("following"),
            "url": u.get("html_url"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "github_free"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "GitHub REST API for public repos (no PAT needed). Optional PAT in vault unlocks private + raises rate limits."
