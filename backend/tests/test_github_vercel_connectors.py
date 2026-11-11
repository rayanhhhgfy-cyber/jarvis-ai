# ====================================================================
# JARVIS OMEGA — GitHub + Vercel connectors tests
# ====================================================================
"""
Tests for the GitHub and Vercel connectors (2026-11-11): read AND
write via the REST APIs, tokens encrypted in the credentials vault,
verified BEFORE storing, never logged or echoed.

* Token storage: vault round-trip, delete, env fallback, and the
  "not connected" error when a write runs without a token.
* API calls: a fake GitHub / Vercel behind httpx.MockTransport.
* Tools: the write tools register at TIER_4_EXTERNAL (approval gate),
  the read tools at TIER_0_OBSERVE.
* Telegram: /connect github|vercel arms a token wait, the pasted
  token is verified then stored, /disconnect removes it, /github and
  /vercel answer from the connectors, /status lists both.

ALL credentials and endpoints here are FAKE. No real GitHub, Vercel
or Turso is touched.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import dm_store, github_connector, vercel_connector
from backend.services.credentials_vault import CredentialsVault
from backend.tools import get_registry
from shared.constants import RiskTier

# --------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------

def _gh_handler(request: httpx.Request) -> httpx.Response:
    """Fake GitHub API."""
    path = request.url.path
    method = request.method
    auth = request.headers.get("Authorization", "")
    if auth != "Bearer fake-gh-token":
        return httpx.Response(401, json={"message": "Bad credentials"}, request=request)
    if method == "GET" and path == "/user":
        return httpx.Response(
            200,
            json={"login": "rayanhhhgfy-cyber", "name": "Rayyan"},
            headers={"x-oauth-scopes": "repo, workflow", "x-ratelimit-remaining": "4999"},
            request=request,
        )
    if method == "GET" and path.startswith("/users/") and path.endswith("/repos"):
        return httpx.Response(200, json=[
            {"name": "jarvis-ai", "full_name": "rayanhhhgfy-cyber/jarvis-ai",
             "description": "Jarvis", "html_url": "https://github.com/r/jarvis-ai",
             "stargazers_count": 3, "language": "Python",
             "default_branch": "main", "updated_at": "2026-11-11T00:00:00Z"},
        ], request=request)
    if method == "GET" and path.endswith("/issues"):
        return httpx.Response(200, json=[
            {"number": 1, "title": "Fix the bug", "state": "open",
             "html_url": "https://github.com/r/x/issues/1",
             "user": {"login": "rayyan"}, "created_at": "2026-11-11T00:00:00Z"},
        ], request=request)
    if method == "POST" and path.endswith("/issues"):
        body = json.loads(request.content.decode())
        return httpx.Response(201, json={
            "number": 42, "title": body.get("title"),
            "html_url": "https://github.com/r/x/issues/42",
        }, request=request)
    if method == "POST" and "/comments" in path:
        return httpx.Response(201, json={
            "id": 9, "html_url": "https://github.com/r/x/issues/1#issuecomment-9",
        }, request=request)
    if method == "POST" and path.endswith("/pulls"):
        return httpx.Response(201, json={
            "number": 7, "html_url": "https://github.com/r/x/pull/7",
        }, request=request)
    if method == "PUT" and path.endswith("/merge"):
        return httpx.Response(200, json={"merged": True, "message": "ok"}, request=request)
    if method == "GET" and "/contents/" in path:
        if "exists.txt" in path:
            return httpx.Response(200, json={"sha": "oldsha123"}, request=request)
        return httpx.Response(404, json={"message": "Not Found"}, request=request)
    if method == "PUT" and "/contents/" in path:
        return httpx.Response(201, json={
            "commit": {"sha": "abc1234def"},
            "content": {"html_url": "https://github.com/r/x/blob/main/new.txt"},
        }, request=request)
    if method == "POST" and path.endswith("/dispatches"):
        return httpx.Response(204, request=request)
    return httpx.Response(404, json={"message": "Not Found"}, request=request)


def _vc_handler(request: httpx.Request) -> httpx.Response:
    """Fake Vercel API."""
    path = request.url.path
    method = request.method
    auth = request.headers.get("Authorization", "")
    if auth != "Bearer fake-vc-token":
        return httpx.Response(403, json={"error": {"message": "Forbidden"}}, request=request)
    if method == "GET" and path == "/v2/user":
        return httpx.Response(200, json={"user": {
            "id": "u1", "username": "rayyan", "email": "r@example.com",
            "name": "Rayyan",
        }}, request=request)
    if method == "GET" and path == "/v9/projects":
        return httpx.Response(200, json={"projects": [
            {"id": "prj_1", "name": "jarvis-frontend", "framework": "nextjs",
             "updatedAt": 1762810000000},
        ]}, request=request)
    if method == "GET" and path == "/v6/deployments":
        return httpx.Response(200, json={"deployments": [
            {"uid": "dpl_1", "name": "jarvis-frontend", "url": "jarvis-frontend-iota.vercel.app",
             "state": "READY", "createdAt": 1762810000000},
        ]}, request=request)
    if method == "GET" and path == "/v13/deployments/dpl_1":
        return httpx.Response(200, json={
            "uid": "dpl_1", "name": "jarvis-frontend",
            "url": "jarvis-frontend-iota.vercel.app", "state": "READY",
            "readyState": "READY", "createdAt": 1762810000000,
        }, request=request)
    if method == "POST" and path == "/v13/deployments":
        return httpx.Response(200, json={
            "id": "dpl_2", "url": "jarvis-frontend-2.vercel.app",
            "readyState": "QUEUED",
        }, request=request)
    if method == "DELETE" and path == "/v12/deployments/dpl_1":
        return httpx.Response(200, json={}, request=request)
    return httpx.Response(404, json={"error": {"message": "not found"}}, request=request)


def _fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=15)


def _fresh_vault(monkeypatch, tmp_path, module, name: str):
    """Point a connector module's vault at a fresh tmp vault."""
    vault = CredentialsVault(storage_path=str(tmp_path / name))
    vault.initialize()
    monkeypatch.setattr(module, "credentials_vault", vault)
    return vault


# --------------------------------------------------------------------
# GitHub connector
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_verify_token_ok(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    info = await github_connector.verify_token(
        "fake-gh-token", client=_fake_client(_gh_handler)
    )
    assert info is not None
    assert info["login"] == "rayanhhhgfy-cyber"
    assert "repo" in info["scopes"]
    assert info["rate_limit_remaining"] == "4999"


@pytest.mark.asyncio
async def test_github_verify_token_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    info = await github_connector.verify_token(
        "wrong-token", client=_fake_client(_gh_handler)
    )
    assert info is None
    assert await github_connector.verify_token("", client=_fake_client(_gh_handler)) is None


def test_github_token_save_delete_round_trip(monkeypatch, tmp_path):
    vault = _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    assert not github_connector.is_connected()
    github_connector.save_token("fake-gh-token")
    assert github_connector.is_connected()
    assert github_connector.token() == "fake-gh-token"
    # Stored encrypted: the raw token never appears in the file.
    blob = (tmp_path / "gh.json").read_text(encoding="utf-8")
    assert "fake-gh-token" not in blob
    assert vault.get("github_pat") == "fake-gh-token"
    assert github_connector.delete_token() is True
    assert not github_connector.is_connected()
    assert github_connector.delete_token() is False


def test_github_token_env_fallback(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-gh-token")
    assert github_connector.token() == "fake-gh-token"
    assert github_connector.is_connected()


@pytest.mark.asyncio
async def test_github_reads(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    github_connector.save_token("fake-gh-token")
    client = _fake_client(_gh_handler)
    repos = await github_connector.list_repos("me", limit=10, client=client)
    assert repos["ok"] and repos["username"] == "rayanhhhgfy-cyber"
    assert repos["repos"][0]["name"] == "jarvis-ai"
    issues = await github_connector.list_issues("o", "r", client=client)
    assert issues["ok"] and issues["issues"][0]["number"] == 1


@pytest.mark.asyncio
async def test_github_writes(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    github_connector.save_token("fake-gh-token")
    client = _fake_client(_gh_handler)
    issue = await github_connector.create_issue("o", "r", "New bug", client=client)
    assert issue["ok"] and issue["number"] == 42
    comment = await github_connector.comment_issue("o", "r", 1, "hi", client=client)
    assert comment["ok"] and comment["id"] == 9
    pr = await github_connector.create_pr("o", "r", "T", "feat", "main", client=client)
    assert pr["ok"] and pr["number"] == 7
    merged = await github_connector.merge_pr("o", "r", 7, client=client)
    assert merged["ok"] and merged["merged"] is True
    created = await github_connector.create_or_update_file(
        "o", "r", "new.txt", "hello", "add file", client=client
    )
    assert created["ok"] and created["sha"] == "abc1234"
    updated = await github_connector.create_or_update_file(
        "o", "r", "exists.txt", "hello2", "edit file", client=client
    )
    assert updated["ok"]
    wf = await github_connector.trigger_workflow("o", "r", "ci.yml", client=client)
    assert wf["ok"] and wf["dispatched"] is True


@pytest.mark.asyncio
async def test_github_write_without_token_fails(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = await github_connector.create_issue("o", "r", "x")
    assert not result["ok"]
    assert "not connected" in result["error"]


# --------------------------------------------------------------------
# Vercel connector
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vercel_verify_token_ok(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, vercel_connector, "vc.json")
    info = await vercel_connector.verify_token(
        "fake-vc-token", client=_fake_client(_vc_handler)
    )
    assert info is not None
    assert info["username"] == "rayyan"
    assert info["email"] == "r@example.com"


@pytest.mark.asyncio
async def test_vercel_verify_token_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, vercel_connector, "vc.json")
    assert await vercel_connector.verify_token(
        "wrong-token", client=_fake_client(_vc_handler)
    ) is None


def test_vercel_token_save_delete_round_trip(monkeypatch, tmp_path):
    vault = _fresh_vault(monkeypatch, tmp_path, vercel_connector, "vc.json")
    assert not vercel_connector.is_connected()
    vercel_connector.save_token("fake-vc-token")
    assert vercel_connector.is_connected()
    blob = (tmp_path / "vc.json").read_text(encoding="utf-8")
    assert "fake-vc-token" not in blob
    assert vault.get("vercel_token") == "fake-vc-token"
    assert vercel_connector.delete_token() is True
    assert not vercel_connector.is_connected()


@pytest.mark.asyncio
async def test_vercel_reads_and_writes(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, vercel_connector, "vc.json")
    vercel_connector.save_token("fake-vc-token")
    client = _fake_client(_vc_handler)
    projects = await vercel_connector.list_projects(client=client)
    assert projects["ok"] and projects["projects"][0]["name"] == "jarvis-frontend"
    deployments = await vercel_connector.list_deployments(client=client)
    assert deployments["ok"] and deployments["deployments"][0]["state"] == "READY"
    one = await vercel_connector.get_deployment("dpl_1", client=client)
    assert one["ok"] and one["url"] == "jarvis-frontend-iota.vercel.app"
    redeployed = await vercel_connector.redeploy("dpl_1", client=client)
    assert redeployed["ok"] and redeployed["id"] == "dpl_2"
    cancelled = await vercel_connector.cancel_deployment("dpl_1", client=client)
    assert cancelled["ok"] and cancelled["cancelled"] is True


@pytest.mark.asyncio
async def test_vercel_write_without_token_fails(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, vercel_connector, "vc.json")
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    result = await vercel_connector.redeploy("dpl_1")
    assert not result["ok"]
    assert "not connected" in result["error"]


# --------------------------------------------------------------------
# Tools: registration + risk tiers
# --------------------------------------------------------------------

def test_connector_tools_registered_with_right_tiers():

    registry = get_registry()
    # GitHub writes: external changes, approval gate.
    for name in (
        "github.create_issue", "github.comment_issue", "github.create_pr",
        "github.merge_pr", "github.create_or_update_file",
        "github.trigger_workflow",
    ):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_4_EXTERNAL, name
    # Vercel reads: observe only.
    for name in (
        "vercel.list_projects", "vercel.list_deployments",
        "vercel.get_deployment", "vercel.list_domains",
    ):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_0_OBSERVE, name
    # Vercel writes: approval gate.
    for name in ("vercel.redeploy", "vercel.cancel_deployment"):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_4_EXTERNAL, name


# --------------------------------------------------------------------
# Telegram: /connect, /disconnect, /github, /vercel, /status
# --------------------------------------------------------------------

def _telegram_app():
    from backend.routers.router_telegram import router

    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


def _prep_webhook(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    _fresh_vault(monkeypatch, tmp_path, github_connector, "gh.json")
    _fresh_vault(monkeypatch, tmp_path, vercel_connector, "vc.json")


@pytest.mark.asyncio
async def test_webhook_connect_github_flow(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch.object(
            github_connector, "verify_token",
            new=AsyncMock(return_value={"login": "rayanhhhgfy-cyber"}),
        ),
    ):
        assert _webhook_post("/connect github", update_id=31).status_code == 200
        assert "token" in mock_send.call_args.args[0].lower()
        assert _webhook_post("fake-gh-token", update_id=32).status_code == 200
    reply = mock_send.call_args.args[0]
    assert "Connected to GitHub" in reply
    assert "rayanhhhgfy-cyber" in reply
    assert "fake-gh-token" not in reply  # the token is never echoed back
    assert github_connector.is_connected()


@pytest.mark.asyncio
async def test_webhook_connect_github_bad_token(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch.object(github_connector, "verify_token", new=AsyncMock(return_value=None)),
    ):
        _webhook_post("/connect github", update_id=33)
        _webhook_post("bad-token", update_id=34)
    assert "didn't work" in mock_send.call_args.args[0]
    assert not github_connector.is_connected()


@pytest.mark.asyncio
async def test_webhook_connect_vercel_flow(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch.object(
            vercel_connector, "verify_token",
            new=AsyncMock(return_value={"username": "rayyan"}),
        ),
    ):
        _webhook_post("/connect vercel", update_id=35)
        _webhook_post("fake-vc-token", update_id=36)
    reply = mock_send.call_args.args[0]
    assert "Connected to Vercel" in reply
    assert "fake-vc-token" not in reply
    assert vercel_connector.is_connected()


@pytest.mark.asyncio
async def test_webhook_disconnect_connectors(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    github_connector.save_token("fake-gh-token")
    vercel_connector.save_token("fake-vc-token")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        _webhook_post("/disconnect github", update_id=37)
        assert "Disconnected GitHub" in mock_send.call_args.args[0]
        assert not github_connector.is_connected()
        _webhook_post("/disconnect vercel", update_id=38)
        assert "Disconnected Vercel" in mock_send.call_args.args[0]
        assert not vercel_connector.is_connected()
        _webhook_post("/disconnect github", update_id=39)
        assert "isn't connected" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_github_and_vercel_commands(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    github_connector.save_token("fake-gh-token")
    vercel_connector.save_token("fake-vc-token")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_client = _fake_client(_gh_handler)
    vc_client = _fake_client(_vc_handler)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch.object(
            github_connector, "list_repos",
            new=AsyncMock(return_value={"ok": True, "username": "rayanhhhgfy-cyber",
                                        "repos": [{"full_name": "rayanhhhgfy-cyber/jarvis-ai",
                                                   "stars": 3, "language": "Python"}]}),
        ),
        patch.object(
            vercel_connector, "list_projects",
            new=AsyncMock(return_value={"ok": True, "projects": [
                {"name": "jarvis-frontend", "framework": "nextjs"}]}),
        ),
    ):
        _webhook_post("/github repos", update_id=40)
        assert "jarvis-ai" in mock_send.call_args.args[0]
        _webhook_post("/vercel projects", update_id=41)
        assert "jarvis-frontend" in mock_send.call_args.args[0]
    assert fake_client is not None and vc_client is not None


@pytest.mark.asyncio
async def test_webhook_connector_commands_need_connection(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        _webhook_post("/github repos", update_id=42)
        assert "isn't connected" in mock_send.call_args.args[0]
        _webhook_post("/vercel projects", update_id=43)
        assert "isn't connected" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_status_lists_connectors(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    github_connector.save_token("fake-gh-token")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    fake_responder.get_status.return_value = {
        "enabled": True, "running": True, "platforms": {},
    }
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch.object(
            github_connector, "status",
            new=AsyncMock(return_value={"connected": True, "login": "rayanhhhgfy-cyber"}),
        ),
        patch.object(
            vercel_connector, "status",
            new=AsyncMock(return_value={"connected": False, "username": None}),
        ),
    ):
        _webhook_post("/status", update_id=44)
    reply = mock_send.call_args.args[0]
    assert "GitHub: connected (rayanhhhgfy-cyber)" in reply
    assert "Vercel: not connected" in reply


def test_connector_commands_registered():
    from backend.services.telegram_notifier import TELEGRAM_COMMANDS

    names = [c["command"] for c in TELEGRAM_COMMANDS]
    assert "github" in names
    assert "vercel" in names
    assert len(names) == 31
