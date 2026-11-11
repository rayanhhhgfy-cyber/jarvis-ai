# ====================================================================
# JARVIS OMEGA — TikTok connector tests
# ====================================================================
"""
Tests for the TikTok connector (2026-11-11): Business Messaging via
OAuth 2.0, tokens encrypted in the credentials vault, verified
BEFORE storing, never logged or echoed.

* OAuth: authorize URL shape, code exchange stores tokens (raw
  values never appear in the vault file), refresh rotates tokens.
* API calls: a fake TikTok behind httpx.MockTransport — the Login
  Kit endpoints on open.tiktokapis.com AND the Business Messaging
  endpoints on business-api.tiktok.com.
* Messaging: list conversations, send a message, 401 refreshes the
  token once and retries, write-without-token fails.
* Tools: the send tool registers at TIER_4_EXTERNAL (approval
  gate), the read tools at TIER_0_OBSERVE.

ALL credentials and endpoints here are FAKE. No real TikTok or
Turso is touched. The Business Messaging host and paths are the
best-known values (see tiktok_connector.py) — the tests pin the
client to those paths; a live call against a real approved app is
still required before claiming they work.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from backend.services import tiktok_connector
from backend.services.credentials_vault import CredentialsVault
from backend.tools import get_registry
from shared.constants import RiskTier

# --------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------

def _tt_handler(request: httpx.Request) -> httpx.Response:
    """Fake TikTok: Login Kit on open.tiktokapis.com, Business
    Messaging on business-api.tiktok.com."""
    host = request.url.host
    path = request.url.path
    method = request.method
    auth = request.headers.get("Authorization", "")

    if host == "open.tiktokapis.com" and path == "/v2/oauth/token/":
        form = {
            k: v[0] for k, v in parse_qs(request.content.decode()).items()
        }
        if form.get("client_key") != "fake-client-key":
            return httpx.Response(
                400,
                json={"error": "invalid_client", "error_description": "bad key"},
                request=request,
            )
        if form.get("client_secret") != "fake-client-secret":
            return httpx.Response(
                400,
                json={"error": "invalid_client", "error_description": "bad secret"},
                request=request,
            )
        if form.get("grant_type") == "authorization_code":
            if form.get("code") != "fake-code":
                return httpx.Response(
                    400,
                    json={"error": "invalid_grant", "error_description": "bad code"},
                    request=request,
                )
            return httpx.Response(200, json={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "open_id": "fake-open-id",
                "expires_in": 7200,
                "refresh_expires_in": 15552000,
                "scope": "user.info.basic,message.list.read,message.list.send",
                "token_type": "Bearer",
            }, request=request)
        if form.get("grant_type") == "refresh_token":
            if form.get("refresh_token") != "fake-refresh-token":
                return httpx.Response(
                    400,
                    json={"error": "invalid_grant", "error_description": "bad refresh"},
                    request=request,
                )
            return httpx.Response(200, json={
                "access_token": "fake-access-token-2",
                "refresh_token": "fake-refresh-token-2",
                "open_id": "fake-open-id",
                "expires_in": 7200,
                "refresh_expires_in": 15552000,
                "scope": "user.info.basic,message.list.read,message.list.send",
                "token_type": "Bearer",
            }, request=request)
        return httpx.Response(
            400, json={"error": "unsupported_grant_type"}, request=request
        )

    if host == "open.tiktokapis.com" and path == "/v2/user/info/":
        if auth in ("Bearer fake-access-token", "Bearer fake-access-token-2"):
            return httpx.Response(200, json={
                "data": {"user": {
                    "open_id": "fake-open-id",
                    "display_name": "Rayyan",
                    "avatar_url": "https://example.com/a.jpg",
                }},
            }, request=request)
        return httpx.Response(
            401, json={"error": "invalid_token"}, request=request
        )

    if host == "business-api.tiktok.com":
        if auth == "Bearer fake-expired-token":
            return httpx.Response(
                401, json={"code": 401, "message": "unauthorized"}, request=request
            )
        if auth not in ("Bearer fake-access-token", "Bearer fake-access-token-2"):
            return httpx.Response(
                401, json={"code": 401, "message": "unauthorized"}, request=request
            )
        if method == "GET" and path == "/business/message/conversation/list/":
            params = dict(request.url.params)
            if params.get("business_id") != "fake-open-id":
                return httpx.Response(
                    200,
                    json={"code": 40001, "message": "invalid business_id", "data": {}},
                    request=request,
                )
            return httpx.Response(200, json={
                "code": 0, "message": "success",
                "data": {
                    "conversations": [
                        {"conversation_id": "conv_1", "up_time": 1762810000000},
                        {"conversation_id": "conv_2", "up_time": 1762800000000},
                    ],
                    "has_more": False, "cursor": 0,
                },
            }, request=request)
        if method == "POST" and path == "/business/message/send/":
            body = json.loads(request.content.decode())
            if body.get("recipient") == "conv_bad":
                return httpx.Response(
                    200,
                    json={"code": 40001, "message": "conversation not found", "data": {}},
                    request=request,
                )
            assert body.get("business_id") == "fake-open-id"
            assert body.get("recipient_type") == "CONVERSATION"
            assert body.get("message_type") == "TEXT"
            assert body.get("text", {}).get("body")
            return httpx.Response(200, json={
                "code": 0, "message": "success",
                "data": {"message": {"message_id": "msg_123"}},
            }, request=request)

    return httpx.Response(404, json={"error": "not found"}, request=request)


def _fake_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_tt_handler), timeout=15)


def _fresh_vault(monkeypatch, tmp_path, name: str = "tt.json"):
    """Point the connector module's vault at a fresh tmp vault."""
    vault = CredentialsVault(storage_path=str(tmp_path / name))
    vault.initialize()
    monkeypatch.setattr(tiktok_connector, "credentials_vault", vault)
    return vault


def _connect(monkeypatch, tmp_path):
    """Fresh vault + app credentials + exchanged tokens."""
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    return _fake_client()


# --------------------------------------------------------------------
# OAuth: authorize URL
# --------------------------------------------------------------------

def test_get_auth_url(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    url = tiktok_connector.get_auth_url(
        "https://jarvis-ai-6c11.onrender.com/api/tiktok/callback",
        scopes=["user.info.basic", "message.list.send"],
        state="abc123",
    )
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/?")
    assert "client_key=fake-client-key" in url
    assert "response_type=code" in url
    assert "scope=user.info.basic%2Cmessage.list.send" in url
    assert "redirect_uri=https%3A%2F%2Fjarvis-ai-6c11.onrender.com" in url
    assert "state=abc123" in url


def test_get_auth_url_default_scopes_include_messaging(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    url = tiktok_connector.get_auth_url("https://example.com/cb")
    assert "message.list.read" in url
    assert "message.list.send" in url


def test_get_auth_url_no_client_key_raises(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="client key"):
        tiktok_connector.get_auth_url("https://example.com/cb")


# --------------------------------------------------------------------
# OAuth: code exchange + refresh
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_ok_stores_tokens_encrypted(monkeypatch, tmp_path):
    vault = _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    result = await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=_fake_client()
    )
    assert result == {"ok": True, "open_id": "fake-open-id"}
    assert tiktok_connector.token() == "fake-access-token"
    assert tiktok_connector.refresh_token() == "fake-refresh-token"
    assert tiktok_connector.open_id() == "fake-open-id"
    assert tiktok_connector.is_connected()
    # Stored encrypted: no raw credential appears in the vault file.
    blob = (tmp_path / "tt.json").read_text(encoding="utf-8")
    assert "fake-access-token" not in blob
    assert "fake-refresh-token" not in blob
    assert "fake-client-secret" not in blob
    assert vault.get("tiktok_access_token") == "fake-access-token"


@pytest.mark.asyncio
async def test_exchange_code_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    result = await tiktok_connector.exchange_code(
        "bad-code", "https://example.com/cb", client=_fake_client()
    )
    assert not result["ok"]
    assert "bad code" in result["error"]
    assert not tiktok_connector.is_connected()


@pytest.mark.asyncio
async def test_exchange_code_no_app_credentials(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    result = await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=_fake_client()
    )
    assert not result["ok"]
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_refresh_access_token_rotates(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=_fake_client()
    )
    new_token = await tiktok_connector.refresh_access_token(client=_fake_client())
    assert new_token == "fake-access-token-2"
    assert tiktok_connector.token() == "fake-access-token-2"
    # TikTok rotated the refresh token too — the new one is persisted.
    assert tiktok_connector.refresh_token() == "fake-refresh-token-2"


@pytest.mark.asyncio
async def test_refresh_access_token_without_refresh_token(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    assert await tiktok_connector.refresh_access_token(client=_fake_client()) is None


@pytest.mark.asyncio
async def test_refresh_access_token_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    tiktok_connector._save_tokens("fake-access-token", "bad-refresh", "fake-open-id")
    assert await tiktok_connector.refresh_access_token(client=_fake_client()) is None


# --------------------------------------------------------------------
# Token storage + verify + status
# --------------------------------------------------------------------

def test_token_delete_round_trip_and_env_fallback(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    assert not tiktok_connector.is_connected()
    tiktok_connector._save_tokens("fake-access-token", "fake-refresh-token", "fake-open-id")
    assert tiktok_connector.is_connected()
    assert tiktok_connector.delete_tokens() is True
    assert not tiktok_connector.is_connected()
    assert tiktok_connector.delete_tokens() is False
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "fake-access-token")
    assert tiktok_connector.token() == "fake-access-token"
    assert tiktok_connector.is_connected()


@pytest.mark.asyncio
async def test_verify_token_ok(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    info = await tiktok_connector.verify_token(
        "fake-access-token", client=_fake_client()
    )
    assert info is not None
    assert info["open_id"] == "fake-open-id"
    assert info["display_name"] == "Rayyan"


@pytest.mark.asyncio
async def test_verify_token_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    assert await tiktok_connector.verify_token(
        "wrong-token", client=_fake_client()
    ) is None
    assert await tiktok_connector.verify_token("", client=_fake_client()) is None


@pytest.mark.asyncio
async def test_status(monkeypatch, tmp_path):
    client = _connect(monkeypatch, tmp_path)
    await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=client
    )
    status = await tiktok_connector.status(client=client)
    assert status == {"connected": True, "display_name": "Rayyan"}
    _fresh_vault(monkeypatch, tmp_path, "tt2.json")
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    assert await tiktok_connector.status(client=client) == {
        "connected": False, "display_name": None,
    }


# --------------------------------------------------------------------
# Business Messaging: conversations + send
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_conversations_ok(monkeypatch, tmp_path):
    client = _connect(monkeypatch, tmp_path)
    await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=client
    )
    result = await tiktok_connector.list_conversations(limit=10, client=client)
    assert result["ok"] and result["count"] == 2
    assert result["conversations"][0]["conversation_id"] == "conv_1"
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_list_conversations_refreshes_on_401(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    # The stored access token is expired; the refresh token is good.
    tiktok_connector._save_tokens(
        "fake-expired-token", "fake-refresh-token", "fake-open-id"
    )
    client = _fake_client()
    result = await tiktok_connector.list_conversations(limit=10, client=client)
    assert result["ok"] and result["count"] == 2
    # The retry used the refreshed token.
    assert tiktok_connector.token() == "fake-access-token-2"


@pytest.mark.asyncio
async def test_list_conversations_without_open_id(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector._save_tokens("fake-access-token", "fake-refresh-token", None)
    result = await tiktok_connector.list_conversations(client=_fake_client())
    assert not result["ok"]
    assert "open_id" in result["error"]


@pytest.mark.asyncio
async def test_list_conversations_business_error(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    tiktok_connector.save_client_credentials("fake-client-key", "fake-client-secret")
    # A stored open_id that does not match the account: the API
    # answers code != 0 inside a 200.
    tiktok_connector._save_tokens(
        "fake-access-token", "fake-refresh-token", "someone-else"
    )
    result = await tiktok_connector.list_conversations(client=_fake_client())
    assert not result["ok"]
    assert "invalid business_id" in result["error"]


@pytest.mark.asyncio
async def test_send_message_ok(monkeypatch, tmp_path):
    client = _connect(monkeypatch, tmp_path)
    await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=client
    )
    result = await tiktok_connector.send_message(
        "conv_1", "Hello, sir!", client=client
    )
    assert result == {"ok": True, "message_id": "msg_123"}


@pytest.mark.asyncio
async def test_send_message_business_error(monkeypatch, tmp_path):
    client = _connect(monkeypatch, tmp_path)
    await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=client
    )
    result = await tiktok_connector.send_message(
        "conv_bad", "Hello", client=client
    )
    assert not result["ok"]
    assert "conversation not found" in result["error"]


@pytest.mark.asyncio
async def test_send_message_validation(monkeypatch, tmp_path):
    client = _connect(monkeypatch, tmp_path)
    await tiktok_connector.exchange_code(
        "fake-code", "https://example.com/cb", client=client
    )
    assert not (await tiktok_connector.send_message("conv_1", "", client=client))["ok"]
    too_long = await tiktok_connector.send_message(
        "conv_1", "x" * 6001, client=client
    )
    assert not too_long["ok"]
    assert "6,000" in too_long["error"]


@pytest.mark.asyncio
async def test_write_without_token_fails(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path)
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    result = await tiktok_connector.send_message("conv_1", "hi")
    assert not result["ok"]
    assert "not connected" in result["error"]
    result = await tiktok_connector.list_conversations(client=_fake_client())
    assert not result["ok"]
    assert "not connected" in result["error"]


# --------------------------------------------------------------------
# Tools: registration + risk tiers
# --------------------------------------------------------------------

def test_connector_tools_registered_with_right_tiers():
    import importlib

    # Importing the plugin registers its tools (side effect).
    importlib.import_module("plugins.tiktok_connector.plugin")

    registry = get_registry()
    for name in ("tiktok.status", "tiktok.list_conversations"):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_0_OBSERVE, name
    tool = registry.get("tiktok.send_message")
    assert tool is not None
    assert tool.risk_tier == RiskTier.TIER_4_EXTERNAL
