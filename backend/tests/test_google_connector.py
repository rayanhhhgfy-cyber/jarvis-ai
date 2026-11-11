# ====================================================================
# JARVIS OMEGA — Google connector tests (OAuth + Gmail + Calendar + Drive)
# ====================================================================
"""
Tests for the Google connector (2026-11-11): one OAuth login unlocks
Gmail, Calendar and Drive. The OAuth client credentials and the
refresh token live encrypted in the vault; access tokens are minted
on demand and never stored.

ALL credentials and endpoints here are FAKE. No real Google is touched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import google_connector
from backend.services.credentials_vault import CredentialsVault
from backend.tools import get_registry
from shared.constants import RiskTier

# --------------------------------------------------------------------
# Fake Google
# --------------------------------------------------------------------

def _google_handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    path = request.url.path
    method = request.method
    if host == "oauth2.googleapis.com" and method == "POST" and path == "/token":
        body = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        if body.get("grant_type") == "authorization_code":
            if body.get("code") != "fake-auth-code":
                return httpx.Response(400, json={"error": "invalid_grant"}, request=request)
            return httpx.Response(200, json={
                "access_token": "fake-access",
                "refresh_token": "fake-refresh",
                "expires_in": 3600,
            }, request=request)
        if body.get("grant_type") == "refresh_token":
            if body.get("refresh_token") != "fake-refresh":
                return httpx.Response(400, json={"error": "invalid_grant"}, request=request)
            return httpx.Response(200, json={
                "access_token": "fake-access",
                "expires_in": 3600,
            }, request=request)
        return httpx.Response(400, json={"error": "unsupported_grant_type"}, request=request)
    auth = request.headers.get("Authorization", "")
    if auth != "Bearer fake-access":
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)
    if host == "gmail.googleapis.com":
        if method == "GET" and path == "/gmail/v1/users/me/profile":
            return httpx.Response(200, json={"emailAddress": "rayanaljamal550@gmail.com"}, request=request)
        if method == "GET" and path == "/gmail/v1/users/me/messages":
            return httpx.Response(200, json={"messages": [
                {"id": "m1", "threadId": "t1"},
                {"id": "m2", "threadId": "t2"},
            ]}, request=request)
        if method == "GET" and path.startswith("/gmail/v1/users/me/messages/"):
            return httpx.Response(200, json={
                "id": "m1",
                "snippet": "Hello sir",
                "payload": {"headers": [
                    {"name": "From", "value": "omar@example.com"},
                    {"name": "To", "value": "rayanaljamal550@gmail.com"},
                    {"name": "Subject", "value": "Test"},
                    {"name": "Date", "value": "Tue, 11 Nov 2026 09:00:00 +0300"},
                ]},
            }, request=request)
        if method == "POST" and path == "/gmail/v1/users/me/messages/send":
            return httpx.Response(200, json={"id": "sent123"}, request=request)
    if host == "www.googleapis.com":
        if method == "GET" and path == "/calendar/v3/calendars/primary/events":
            return httpx.Response(200, json={"items": [
                {"id": "e1", "summary": "Football",
                 "start": {"dateTime": "2026-11-11T17:00:00+03:00"},
                 "end": {"dateTime": "2026-11-11T18:00:00+03:00"}},
            ]}, request=request)
        if method == "POST" and path == "/calendar/v3/calendars/primary/events":
            return httpx.Response(200, json={
                "id": "e2", "htmlLink": "https://calendar.google.com/event?eid=e2",
            }, request=request)
        if method == "GET" and path == "/drive/v3/files":
            return httpx.Response(200, json={"files": [
                {"id": "f1", "name": "notes.pdf", "mimeType": "application/pdf",
                 "modifiedTime": "2026-11-10T00:00:00Z",
                 "webViewLink": "https://drive.google.com/file/d/f1"},
            ]}, request=request)
        if method == "GET" and path.startswith("/drive/v3/files/"):
            return httpx.Response(200, json={
                "id": "f1", "name": "notes.pdf", "mimeType": "application/pdf",
                "modifiedTime": "2026-11-10T00:00:00Z", "size": "1234",
                "webViewLink": "https://drive.google.com/file/d/f1",
            }, request=request)
    return httpx.Response(404, json={"error": "not found"}, request=request)


def _fake_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_google_handler), timeout=15)


def _prep(monkeypatch, tmp_path):
    vault = CredentialsVault(storage_path=str(tmp_path / "google.json"))
    vault.initialize()
    monkeypatch.setattr(google_connector, "credentials_vault", vault)
    google_connector.save_client("fake-client-id", "fake-client-secret")
    return vault


# --------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------

def test_google_auth_url_needs_client(monkeypatch, tmp_path):
    vault = CredentialsVault(storage_path=str(tmp_path / "google.json"))
    vault.initialize()
    monkeypatch.setattr(google_connector, "credentials_vault", vault)
    assert google_connector.get_auth_url() is None
    google_connector.save_client("fake-client-id", "fake-client-secret")
    url = google_connector.get_auth_url()
    assert url is not None
    assert "accounts.google.com" in url
    assert "fake-client-id" in url
    assert "gmail" in url and "calendar" in url and "drive" in url


@pytest.mark.asyncio
async def test_google_exchange_code_stores_refresh(monkeypatch, tmp_path):
    vault = _prep(monkeypatch, tmp_path)
    result = await google_connector.exchange_code("fake-auth-code", client=_fake_client())
    assert result["ok"] is True
    assert result["email"] == "rayanaljamal550@gmail.com"
    assert google_connector.is_connected()
    assert vault.get("google_refresh_token") == "fake-refresh"
    blob = (tmp_path / "google.json").read_text(encoding="utf-8")
    assert "fake-refresh" not in blob
    assert "fake-client-secret" not in blob


@pytest.mark.asyncio
async def test_google_exchange_code_bad(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    result = await google_connector.exchange_code("wrong-code", client=_fake_client())
    assert result["ok"] is False
    assert not google_connector.is_connected()


@pytest.mark.asyncio
async def test_google_access_token_refresh(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_refresh_token("fake-refresh")
    token = await google_connector.get_access_token(client=_fake_client())
    assert token == "fake-access"
    google_connector.save_refresh_token("bad-refresh")
    assert await google_connector.get_access_token(client=_fake_client()) is None


def test_google_delete_all(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_refresh_token("fake-refresh")
    assert google_connector.delete_all() is True
    assert not google_connector.is_connected()
    assert not google_connector.has_client()
    assert google_connector.delete_all() is False


# --------------------------------------------------------------------
# Gmail / Calendar / Drive
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_gmail(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_refresh_token("fake-refresh")
    client = _fake_client()
    messages = await google_connector.list_messages(client=client)
    assert messages["ok"] and messages["count"] == 2
    one = await google_connector.get_message("m1", client=client)
    assert one["ok"] and one["subject"] == "Test"
    assert one["from"] == "omar@example.com"
    sent = await google_connector.send_message("a@b.com", "Hi", "Hello", client=client)
    assert sent["ok"] and sent["id"] == "sent123"


@pytest.mark.asyncio
async def test_google_calendar(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_refresh_token("fake-refresh")
    client = _fake_client()
    events = await google_connector.list_events(client=client)
    assert events["ok"] and events["events"][0]["summary"] == "Football"
    created = await google_connector.create_event(
        "Study", "2026-11-12T10:00:00+03:00", "2026-11-12T11:00:00+03:00", client=client
    )
    assert created["ok"] and created["id"] == "e2"


@pytest.mark.asyncio
async def test_google_drive(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_refresh_token("fake-refresh")
    client = _fake_client()
    files = await google_connector.list_files(client=client)
    assert files["ok"] and files["files"][0]["name"] == "notes.pdf"
    found = await google_connector.search_files("notes", client=client)
    assert found["ok"] and found["count"] == 1
    one = await google_connector.get_file("f1", client=client)
    assert one["ok"] and one["size"] == "1234"


@pytest.mark.asyncio
async def test_google_api_without_connection_fails(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    result = await google_connector.list_messages()
    assert not result["ok"]
    assert "not connected" in result["error"]


# --------------------------------------------------------------------
# Tools: registration + risk tiers
# --------------------------------------------------------------------

def test_google_tools_registered_with_right_tiers():
    import importlib

    # Importing the plugin module registers its tools (importlib, not a
    # bare import, so ruff cannot strip it as unused).
    importlib.import_module("plugins.google.plugin")

    registry = get_registry()
    for name in (
        "google.list_messages", "google.get_message", "google.list_events",
        "google.list_files", "google.search_files",
    ):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_0_OBSERVE, name
    for name in ("google.send_message", "google.create_event"):
        tool = registry.get(name)
        assert tool is not None, name
        assert tool.risk_tier == RiskTier.TIER_4_EXTERNAL, name


# --------------------------------------------------------------------
# OAuth callback route
# --------------------------------------------------------------------

def test_google_oauth_callback_success(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from backend.routers.router_oauth import router

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    with patch.object(
        google_connector, "exchange_code",
        new=AsyncMock(return_value={"ok": True, "email": "rayanaljamal550@gmail.com"}),
    ):
        resp = client.get("/api/oauth/google/callback?code=fake-auth-code&state=telegram")
    assert resp.status_code == 200
    assert "Google connected" in resp.text
    assert "rayanaljamal550@gmail.com" in resp.text


def test_google_oauth_callback_error(monkeypatch, tmp_path):
    from backend.routers.router_oauth import router

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    resp = client.get("/api/oauth/google/callback?error=access_denied")
    assert resp.status_code == 200
    assert "failed" in resp.text
