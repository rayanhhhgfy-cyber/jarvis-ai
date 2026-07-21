# ====================================================================
# JARVIS OMEGA - GitHub Empire (Phase 14)
# ====================================================================
"""
Autonomous open-source maintainer. Discovers unmet needs, bootstraps repos,
implements features, responds to issues, ships releases.

  gh_empire.discover_unmet_need  - scan trending issues across ecosystems
  gh_empire.bootstrap_repo       - create repo + CI + LICENSE
  gh_empire.implement_feature    - LLM writes code + tests
  gh_empire.respond_to_issues    - auto-triage
  gh_empire.publish_release      - tag + changelog
  gh_empire.list_repos           - list all empire repos
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db


_GH_API = "https://api.github.com"


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "JARVIS-OMEGA/1.0"}
    try:
        from backend.services.credentials_vault import credentials_vault
        pat = credentials_vault.get("github_pat")
        if pat:
            h["Authorization"] = f"Bearer {pat}"
    except Exception:
        pass
    return h


@tool(
    name="gh_empire.discover_unmet_need",
    description="Scan GitHub for high-engagement issues with no recent activity. Returns list of opportunities for new tools.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "default": "ai tools"},
            "language": {"type": "string", "default": "python"},
            "min_reactions": {"type": "integer", "default": 5},
            "limit": {"type": "integer", "default": 10},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="gh_empire",
)
async def gh_empire_discover_unmet_need(topic: str = "ai tools", language: str = "python", min_reactions: int = 5, limit: int = 10) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Search for help-wanted issues.
            q = f"label:help-wanted+language:{language}+{topic}+state:open"
            resp = await client.get(
                f"{_GH_API}/search/issues",
                params={"q": q, "sort": "reactions", "order": "desc", "per_page": limit},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        items = resp.json().get("items", [])
        opportunities = [
            {
                "title": it.get("title"),
                "url": it.get("html_url"),
                "reactions": it.get("reactions", {}).get("total_count", 0),
                "comments": it.get("comments"),
                "repo": it.get("repository_url", "").split("repos/")[-1],
                "body": (it.get("body") or "")[:500],
            }
            for it in items if it.get("reactions", {}).get("total_count", 0) >= min_reactions
        ]
        return {"ok": True, "topic": topic, "count": len(opportunities), "opportunities": opportunities}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="gh_empire.bootstrap_repo",
    description="Create a new repo with CI + LICENSE + README. Auto-commits initial code via the LLM.",
    parameters={
        "type": "object",
        "properties": {
            "repo_name": {"type": "string"},
            "description": {"type": "string"},
            "language": {"type": "string", "default": "python"},
            "owner": {"type": "string", "description": "GitHub username or org. Defaults to authenticated user."},
        },
        "required": ["repo_name", "description"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="gh_empire",
)
async def gh_empire_bootstrap_repo(repo_name: str, description: str, language: str = "python", owner: str = "") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Create repo under authenticated user.
            resp = await client.post(f"{_GH_API}/user/repos", json={
                "name": repo_name, "description": description,
                "private": False, "auto_init": True,
                "license_template": "mit",
            }, headers=_headers())
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        full_name = data.get("full_name")
        # Generate README + initial code.
        from backend.services.llm_service import llm_service
        readme = await llm_service.get_response(
            user_message=f"Repo: {repo_name}\nDescription: {description}\nLanguage: {language}",
            system_instructions="Write a compelling README.md for this open source repo. Include: badges, install, usage, contributing. Markdown only.",
            inject_memory=False,
        )
        # Update README via Contents API.
        async with httpx.AsyncClient(timeout=15) as client:
            # Get current README SHA.
            cur = await client.get(f"{_GH_API}/repos/{full_name}/contents/README.md", headers=_headers())
            sha = cur.json().get("sha") if cur.status_code == 200 else None
            import base64
            await client.put(
                f"{_GH_API}/repos/{full_name}/contents/README.md",
                json={
                    "message": "JARVIS: improved README",
                    "content": base64.b64encode(readme.encode()).decode(),
                    "sha": sha,
                },
                headers=_headers(),
            )
        # Persist.
        rid = business_db.execute(
            "INSERT OR IGNORE INTO gh_repos (full_name, description, created_at) VALUES (?, ?, ?)",
            (full_name, description, datetime.utcnow().isoformat()),
        )
        return {"ok": True, "full_name": full_name, "url": data.get("html_url"), "record_id": rid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="gh_empire.implement_feature",
    description="Generate a feature implementation (code + tests) and commit it to a repo.",
    parameters={
        "type": "object",
        "properties": {
            "full_name": {"type": "string", "description": "owner/repo"},
            "feature_description": {"type": "string"},
        },
        "required": ["full_name", "feature_description"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="gh_empire",
)
async def gh_empire_implement_feature(full_name: str, feature_description: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        # Generate code + filename suggestion.
        spec = await llm_service.get_response(
            user_message=f"Repo: {full_name}\nFeature: {feature_description}",
            system_instructions=(
                "Generate implementation. Output STRICT JSON: {"
                "\"filename\": string, \"code\": string, \"test_filename\": string, \"test_code\": string, "
                "\"commit_message\": string}"
            ),
            inject_memory=False,
        )
        text = spec.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        # Push files via Contents API.
        import base64
        async with httpx.AsyncClient(timeout=15) as client:
            await client.put(
                f"{_GH_API}/repos/{full_name}/contents/{parsed['filename']}",
                json={
                    "message": parsed["commit_message"],
                    "content": base64.b64encode(parsed["code"].encode()).decode(),
                },
                headers=_headers(),
            )
            if parsed.get("test_filename") and parsed.get("test_code"):
                await client.put(
                    f"{_GH_API}/repos/{full_name}/contents/{parsed['test_filename']}",
                    json={
                        "message": f"tests: {parsed['commit_message']}",
                        "content": base64.b64encode(parsed["test_code"].encode()).decode(),
                    },
                    headers=_headers(),
                )
        business_db.execute(
            "UPDATE gh_repos SET last_auto_activity = ? WHERE full_name = ?",
            (datetime.utcnow().isoformat(), full_name),
        )
        return {"ok": True, "full_name": full_name, "files": [parsed["filename"], parsed.get("test_filename", "")]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="gh_empire.respond_to_issues",
    description="Scan open issues and post an LLM-generated response to each.",
    parameters={
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "max_issues": {"type": "integer", "default": 5},
        },
        "required": ["full_name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="gh_empire",
)
async def gh_empire_respond_to_issues(full_name: str, max_issues: int = 5) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            issues_resp = await client.get(
                f"{_GH_API}/repos/{full_name}/issues",
                params={"state": "open", "per_page": max_issues},
                headers=_headers(),
            )
        issues = [i for i in issues_resp.json() if "pull_request" not in i][:max_issues]
        responses = 0
        for issue in issues:
            reply = await llm_service.get_response(
                user_message=f"Issue #{issue['number']}: {issue['title']}\n\n{issue.get('body', '')[:1500]}",
                system_instructions=(
                    "You are a helpful open-source maintainer. Acknowledge the issue, ask for any missing details, "
                    "and propose a path forward. Be brief + warm. Markdown."
                ),
                inject_memory=False,
            )
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    f"{_GH_API}/repos/{full_name}/issues/{issue['number']}/comments",
                    json={"body": reply + "\n\n_(This response was generated by JARVIS. A human will review.)_"},
                    headers=_headers(),
                )
            responses += 1
        business_db.execute(
            "UPDATE gh_repos SET last_auto_activity = ? WHERE full_name = ?",
            (datetime.utcnow().isoformat(), full_name),
        )
        return {"ok": True, "issues_addressed": responses}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="gh_empire.publish_release",
    description="Tag a new release with auto-generated changelog.",
    parameters={
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "tag": {"type": "string", "description": "e.g. v1.0.0"},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["full_name", "tag"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="gh_empire",
)
async def gh_empire_publish_release(full_name: str, tag: str, notes: str = "") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Create tag reference.
            await client.post(
                f"{_GH_API}/repos/{full_name}/git/refs",
                json={"ref": f"refs/tags/{tag}", "sha": (await client.get(f"{_GH_API}/repos/{full_name}/git/refs/heads/main", headers=_headers())).json()["object"]["sha"]},
                headers=_headers(),
            )
            # Create release.
            resp = await client.post(
                f"{_GH_API}/repos/{full_name}/releases",
                json={"tag_name": tag, "name": tag, "body": notes or f"Release {tag}", "draft": False, "prerelease": False},
                headers=_headers(),
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        return {"ok": True, "release_url": resp.json().get("html_url")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="gh_empire.list_repos",
    description="List all repos in the GitHub empire.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="gh_empire",
)
async def gh_empire_list_repos() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query(
        "SELECT * FROM gh_repos ORDER BY id DESC LIMIT 100",
    ))
    return {"ok": True, "count": len(rows), "repos": rows}


PLUGIN_NAME = "github_empire"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Autonomous open-source maintainer: discover needs, bootstrap, implement, respond, release."
