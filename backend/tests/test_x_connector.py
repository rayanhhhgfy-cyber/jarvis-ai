# ====================================================================
# JARVIS OMEGA — X (Twitter) connector tests
# ====================================================================
"""
Tests for the X connector (2026-11-11): DMs via the X API v2,
OAuth 2.0 Authorization Code with PKCE, user context.

* OAuth: PKCE pair generation, code exchange stores tokens encrypted
  (raw tokens never appear in the vault file), refresh rotates the
  pair, bad codes fail.
* Token storage: vault round-trip, delete, env fallback, and the
  "not connected" error when a write runs without a token.
* API calls: a fake X behind httpx.MockTransport.
* Tools: the write tools register at TIER_4_EXTERNAL (approval gate),
  the read tools at TIER_0_OBSERVE.

ALL credentials and endpoints here are FAKE. No real X or Turso is
touched. Note: X has no conversation-list endpoint — the connector
derives the conversation list from GET /2/dm_events, grouped by
dm_conversation_id.
"""

from __future__ import annotations

import base64
import hashlib
import urllib.parse
from unittest.mock import patch

import httpx
import pytest

from backend.services import x_connector
from backend.services.credentials_vault import CredentialsVault
from backend.tools import get_registry
from shared.constants import RiskTier

# --------------------------------------------------------------------
# Fake
# --------------------------------------------------------------------

_FAKE_EVENTS = [
    {"id": "e3", "event_type": "MessageCreate", "text": "hello there",
     "sender_id": "999", "dm_conversation_id": "c2",
     "created_at": "2026-11-11T10:00:00Z"},
    {"id": "e2", "event_type": "MessageCreate", "text": "hi",
     "sender_id": "12345", "dm_conversation_id": "c1",
     "created_at": "2026-11-11T09:00:00Z"},
    {"id": "e1", "event_type": "MessageCreate", "text": "first",
     "sender_id": "999", "dm_conversation_id": "c1",
     "created_at": "2026-11-11T08:00:00Z"},
]


def _x_handler(request: httpx.Request) -> httpx.Response:
    """Fake X API v2."""
    path = request.url.path
    method = request.method
    auth = request.headers.get("Authorization", "")

    if method == "POST" and path == "/2/oauth2/token":
        form = urllib.parse.parse_qs(request.content.decode())
        grant = (form.get("grant_type") or [""])[0]
        if grant == "authorization_code" and (form.get("code") or [""])[0] == "fake-code":
            return httpx.Response(200, json={
                "token_type": "Bearer", "expires_in": 7200,
                "access_token": "fake-x-access",
                "refresh_token": "fake-x-refresh",
                "scope": "tweet.read users.read dm.read dm.write offline.access",
            }, request=request)
        if grant == "refresh_token" and (form.get("refresh_token") or [""])[0] == "fake-x-refresh":
            return httpx.Response(200, json={
                "token_type": "Bearer", "expires_in": 7200,
                "access_token": "fake-x-access-2",
                "refresh_token": "fake-x-refresh-2",
                "scope": "tweet.read users.read dm.read dm.write offline.access",
            }, request=request)
        return httpx.Response(400, json={
            "error": "invalid_grant",
            "error_description": "Value passed for the token was invalid.",
        }, request=request)

    if auth not in ("Bearer fake-x-access", "Bearer fake-x-access-2"):
        return httpx.Response(401, json={
            "errors": [{"message": "Unauthorized"}],
        }, request=request)
    if method == "GET" and path == "/2/users/me":
        return httpx.Response(200, json={"data": {
            "id": "12345", "name": "Rayyan", "username": "RayyanAljamal",
        }}, request=request)
    if method == "GET" and path == "/2/dm_events":
        return httpx.Response(200, json={
            "data": _FAKE_EVENTS, "meta": {"result_count": 3},
        }, request=request)
    if method == "GET" and path == "/2/dm_conversations/c1/dm_events":
        return httpx.Response(200, json={
            "data": [_FAKE_EVENTS[1], _FAKE_EVENTS[2]],
            "meta": {"result_count": 2},
        }, request=request)
    if method == "POST" and path == "/2/dm_conversations/c1/messages":
        return httpx.Response(201, json={"data": {
            "dm_conversation_id": "c1", "dm_event_id": "m100",
        }}, request=request)
    if method == "POST" and path == "/2/dm_conversations/with/999/messages":
        return httpx.Response(201, json={"data": {
            "dm_conversation_id": "c9", "dm_event_id": "m101",
        }}, request=request)
    return httpx.Response(404, json={
        "errors": [{"message": "Not Found"}],
    }, request=request)


def _fake_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_x_handler), timeout=15)


def _fresh_vault(monkeypatch, tmp_path, name: str = "x.json"):
    """Point the X connector's vault at a fresh tmp vault."""
    vault = CredentialsVault(storage_path=str(tmp_path / name))
    vault.initialize()
    monkeypatch.setattr(x_connector, "credentials_vault", vault)
    return vault


def _connect(monkeypatch, tmp_path):
    """Fresh vault + saved client credentials + saved user tokens."""
    _fresh_vault(monkeypatch, tmp_path)
    x_connector.save_client_credentials("fake-client-id", "fake-client-secret")
    x_connector.save_tokens("fake-x-access", "fake-x-refresh")


# --------------------------------------------------------------------
# OAuth / PKCE
# --------------------------------------------------------------------

def test_get_auth_url_pkce(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    x_connector.save_client_credentials("fake-client-id", "fake-client-secret")
    result = x_connector.get_auth_url(
        "https://example.com/callback",
        scopes=["tweet.read", "users.read", "dm.read", "dm.write", "offline.access"],
        state="test-state",
    )
    url = result["url"]
    assert url.startswith("https://twitter.com/i/oauth2/authorize?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["fake-client-id"]
    assert query["redirect_uri"] == ["https://example.com/callback"]
    assert query["state"] == ["test-state"]
    assert query["code_challenge_method"] == ["S256"]
    # The challenge is base64url(sha256(verifier)), no padding.
    verifier = result["code_verifier"]
    assert len(verifier) == 43
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert query["code_challenge"] == [expected]
    assert result["code_challenge"] == expected
    assert "dm.read" in query["scope"][0]
    assert "offline.access" in query["scope"][0]


def test_get_auth_url_defaults(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    result = x_connector.get_auth_url("https://example.com/callback")
    assert result["state"]
    assert result["code_verifier"] != result["code_challenge"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(result["url"]).query)
    assert "dm.write" in query["scope"][0]
    assert "offline.access" in query["scope"][0]


@pytest.mark.asyncio
async def test_exchange_code_stores_tokens(monkeypatch, tmp_path):
    vault = _fresh_vault(monkeypatch, tmp_path)
    x_connector.save_client_credentials("fake-client-id", "fake-client-secret")
    result = await x_connector.exchange_code(
        "fake-code", "fake-verifier", "https://example.com/callback",
        client=_fake_client(),
    )
    assert result["ok"] is True
    assert result["username"] == "RayyanAljamal"
    assert x_connector.token() == "fake-x-access"
    assert x_connector.refresh_token_value() == "fake-x-refresh"
    assert vault.get("x_access_token") == "fake-x-access"
    # Stored encrypted: the raw tokens never appear in the file.
    blob = (tmp_path / "x.json").read_text(encoding="utf-8")
    assert "fake-x-access" not in blob
    assert "fake-x-refresh" not in blob
    assert "fake-client-secret" not in blob


@pytest.mark.asyncio
async def test_exchange_code_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    x_connector.save_client_credentials("fake-client-id", "fake-client-secret")
    result = await x_connector.exchange_code(
        "wrong-code", "fake-verifier", "https://example.com/callback",
        client=_fake_client(),
    )
    assert result["ok"] is False
    assert not x_connector.is_connected()


@pytest.mark.asyncio
async def test_exchange_code_needs_client_credentials(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    result = await x_connector.exchange_code(
        "fake-code", "fake-verifier", "https://example.com/callback",
        client=_fake_client(),
    )
    assert result["ok"] is False
    assert "credentials" in result["error"]


@pytest.mark.asyncio
async def test_refresh_access_token(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    new_token = await x_connector.refresh_access_token(client=_fake_client())
    assert new_token == "fake-x-access-2"
    assert x_connector.token() == "fake-x-access-2"
    assert x_connector.refresh_token_value() == "fake-x-refresh-2"


@pytest.mark.asyncio
async def test_refresh_without_token_returns_none(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    assert await x_connector.refresh_access_token(client=_fake_client()) is None


# --------------------------------------------------------------------
# Token storage + verify + status
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_token_ok(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    info = await x_connector.verify_token("fake-x-access", client=_fake_client())
    assert info is not None
    assert info["username"] == "RayyanAljamal"
    assert info["id"] == "12345"
    assert info["name"] == "Rayyan"


@pytest.mark.asyncio
async def test_verify_token_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    assert await x_connector.verify_token("wrong-token", client=_fake_client()) is None
    assert await x_connector.verify_token("", client=_fake_client()) is None


def test_token_save_delete_round_trip(monkeypatch, tmp_path):
    vault = _fresh_vault(monkeypatch, tmp_path)
    assert not x_connector.is_connected()
    x_connector.save_tokens("fake-x-access", "fake-x-refresh")
    assert x_connector.is_connected()
    assert x_connector.token() == "fake-x-access"
    assert x_connector.refresh_token_value() == "fake-x-refresh"
    assert vault.get("x_access_token") == "fake-x-access"
    assert x_connector.delete_tokens() is True
    assert not x_connector.is_connected()
    assert x_connector.delete_tokens() is False
    x_connector.save_client_credentials("fake-client-id", "fake-client-secret")
    assert x_connector.delete_all() is True
    assert x_connector.client_id() is None


def test_token_env_fallback(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("X_ACCESS_TOKEN", "fake-x-access")
    assert x_connector.token() == "fake-x-access"
    assert x_connector.is_connected()


@pytest.mark.asyncio
async def test_status(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    with patch.object(
        x_connector, "verify_token",
        return_value={"id": "12345", "username": "RayyanAljamal"},
    ):
        assert await x_connector.status() == {
            "connected": True, "username": "RayyanAljamal",
        }
    _fresh_vault(monkeypatch, tmp_path, name="x2.json")
    monkeypatch.delenv("X_ACCESS_TOKEN", raising=False)
    assert await x_connector.status() == {"connected": False, "username": None}


# --------------------------------------------------------------------
# DM reads
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_dm_conversations(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await x_connector.list_dm_conversations(limit=10, client=_fake_client())
    assert result["ok"]
    assert result["count"] == 2
    convs = result["conversations"]
    # Newest first: c2 (event e3) before c1 (latest event e2, not e1).
    assert convs[0]["dm_conversation_id"] == "c2"
    assert convs[0]["last_event_id"] == "e3"
    assert convs[0]["last_text"] == "hello there"
    assert convs[1]["dm_conversation_id"] == "c1"
    assert convs[1]["last_event_id"] == "e2"
    assert convs[1]["last_text"] == "hi"


@pytest.mark.asyncio
async def test_list_dm_conversations_limit(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await x_connector.list_dm_conversations(limit=1, client=_fake_client())
    assert result["ok"] and result["count"] == 1
    assert result["conversations"][0]["dm_conversation_id"] == "c2"


@pytest.mark.asyncio
async def test_list_dm_events(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await x_connector.list_dm_events("c1", limit=10, client=_fake_client())
    assert result["ok"]
    assert result["count"] == 2
    assert result["events"][0]["id"] == "e2"
    assert result["events"][0]["text"] == "hi"
    assert result["events"][1]["id"] == "e1"


# --------------------------------------------------------------------
# DM writes
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_dm(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await x_connector.send_dm("c1", "hello", client=_fake_client())
    assert result["ok"]
    assert result["conversation_id"] == "c1"
    assert result["message_id"] == "m100"


@pytest.mark.asyncio
async def test_create_dm_conversation(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await x_connector.create_dm_conversation("999", "hello", client=_fake_client())
    assert result["ok"]
    assert result["conversation_id"] == "c9"
    assert result["message_id"] == "m101"


@pytest.mark.asyncio
async def test_write_without_token_fails(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    monkeypatch.delenv("X_ACCESS_TOKEN", raising=False)
    result = await x_connector.send_dm("c1", "hello")
    assert not result["ok"]
    assert "not connected" in result["error"]
    result = await x_connector.create_dm_conversation("999", "hello")
    assert not result["ok"]
    assert "not connected" in result["error"]


# --------------------------------------------------------------------
# Tools: registration + risk tiers
# --------------------------------------------------------------------

def test_connector_tools_registered_with_right_tiers():
    import plugins.x_connector.plugin  # noqa: F401  (registers tools)

    registry = get_registry()
    # X reads: observe only.
    for name in ("x.status", "x.list_dm_conversations", "x.list_dm_events"):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_0_OBSERVE, name
    # X writes: external changes, approval gate.
    for name in ("x.send_dm", "x.create_dm_conversation"):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_4_EXTERNAL, name
