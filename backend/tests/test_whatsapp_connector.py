# ====================================================================
# JARVIS OMEGA — WhatsApp connector tests
# ====================================================================
"""
Tests for the WhatsApp connector (2026-11-11): send via the WhatsApp
Cloud API (Meta), token + phone number id encrypted in the credentials
vault, token verified BEFORE storing, never logged or echoed.

* Token storage: vault round-trip, delete, env fallback, and the
  "not connected" error when a send runs without a token or without
  a phone number id.
* API calls: a fake Cloud API behind httpx.MockTransport.
* Tools: the send tools register at TIER_4_EXTERNAL (approval gate),
  the status tool at TIER_0_OBSERVE.

ALL credentials and endpoints here are FAKE. No real Meta, WhatsApp
or Turso is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.services import whatsapp_connector
from backend.services.credentials_vault import CredentialsVault
from backend.tools import get_registry
from shared.constants import RiskTier

_FAKE_PHONE_ID = "123456789012345"


# --------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------

def _wa_handler(request: httpx.Request) -> httpx.Response:
    """Fake WhatsApp Cloud API (graph.facebook.com/v18.0)."""
    path = request.url.path
    method = request.method
    auth = request.headers.get("Authorization", "")
    if auth != "Bearer fake-wa-token":
        return httpx.Response(401, json={"error": {"message": "Invalid OAuth access token"}}, request=request)
    if method == "GET" and path == "/v18.0/me":
        return httpx.Response(200, json={
            "id": "act_987654321", "name": "Jarvis Business",
        }, request=request)
    if method == "POST" and path == f"/v18.0/{_FAKE_PHONE_ID}/messages":
        body = json.loads(request.content.decode())
        if body.get("status") == "read":
            return httpx.Response(200, json={"success": True}, request=request)
        if body.get("type") == "text":
            assert body.get("messaging_product") == "whatsapp"
            assert body.get("to") == "962788809843"
            assert body.get("text", {}).get("body") == "Hello, sir."
            return httpx.Response(200, json={
                "messages": [{"id": "wamid.text123"}],
            }, request=request)
        if body.get("type") == "template":
            assert body.get("template", {}).get("name") == "hello_world"
            assert body.get("template", {}).get("language", {}).get("code") == "en_US"
            return httpx.Response(200, json={
                "messages": [{"id": "wamid.tpl123"}],
            }, request=request)
        return httpx.Response(400, json={"error": {"message": "unknown type"}}, request=request)
    return httpx.Response(404, json={"error": {"message": "not found"}}, request=request)


def _fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=15)


def _fresh_vault(monkeypatch, tmp_path, module, name: str):
    """Point a connector module's vault at a fresh tmp vault."""
    vault = CredentialsVault(storage_path=str(tmp_path / name))
    vault.initialize()
    monkeypatch.setattr(module, "credentials_vault", vault)
    return vault


def _connect(monkeypatch, tmp_path):
    """Store a fake token + phone number id in a fresh vault."""
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    whatsapp_connector.save_token("fake-wa-token")
    whatsapp_connector.save_phone_number_id(_FAKE_PHONE_ID)


# --------------------------------------------------------------------
# Verify + token storage
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_token_ok(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    whatsapp_connector.save_phone_number_id(_FAKE_PHONE_ID)
    info = await whatsapp_connector.verify_token(
        "fake-wa-token", client=_fake_client(_wa_handler)
    )
    assert info is not None
    assert info["account_id"] == "act_987654321"
    assert info["phone_number_id"] == _FAKE_PHONE_ID


@pytest.mark.asyncio
async def test_verify_token_bad(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    info = await whatsapp_connector.verify_token(
        "wrong-token", client=_fake_client(_wa_handler)
    )
    assert info is None
    assert await whatsapp_connector.verify_token("", client=_fake_client(_wa_handler)) is None


def test_token_save_delete_round_trip(monkeypatch, tmp_path):
    vault = _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    assert not whatsapp_connector.is_connected()
    whatsapp_connector.save_token("fake-wa-token")
    # Token alone is not enough: the phone number id is also required.
    assert not whatsapp_connector.is_connected()
    whatsapp_connector.save_phone_number_id(_FAKE_PHONE_ID)
    assert whatsapp_connector.is_connected()
    assert whatsapp_connector.token() == "fake-wa-token"
    assert whatsapp_connector.phone_number_id() == _FAKE_PHONE_ID
    # Stored encrypted: the raw values never appear in the file.
    blob = (tmp_path / "wa.json").read_text(encoding="utf-8")
    assert "fake-wa-token" not in blob
    assert _FAKE_PHONE_ID not in blob
    assert vault.get("whatsapp_token") == "fake-wa-token"
    assert vault.get("whatsapp_phone_number_id") == _FAKE_PHONE_ID
    assert whatsapp_connector.delete_token() is True
    assert not whatsapp_connector.is_connected()
    assert whatsapp_connector.delete_token() is False
    assert whatsapp_connector.delete_phone_number_id() is True
    assert whatsapp_connector.delete_phone_number_id() is False


def test_token_env_fallback(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    monkeypatch.setenv("WHATSAPP_TOKEN", "fake-wa-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", _FAKE_PHONE_ID)
    assert whatsapp_connector.token() == "fake-wa-token"
    assert whatsapp_connector.phone_number_id() == _FAKE_PHONE_ID
    assert whatsapp_connector.is_connected()


# --------------------------------------------------------------------
# Status + sends
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_connected(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await whatsapp_connector.status(client=_fake_client(_wa_handler))
    assert result == {"connected": True, "phone_number_id": _FAKE_PHONE_ID}


@pytest.mark.asyncio
async def test_status_not_connected(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    result = await whatsapp_connector.status(client=_fake_client(_wa_handler))
    assert result == {"connected": False, "phone_number_id": None}


@pytest.mark.asyncio
async def test_send_message(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await whatsapp_connector.send_message(
        "962788809843", "Hello, sir.", client=_fake_client(_wa_handler)
    )
    assert result == {"ok": True, "message_id": "wamid.text123"}


@pytest.mark.asyncio
async def test_send_template(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await whatsapp_connector.send_template(
        "962788809843", "hello_world", client=_fake_client(_wa_handler)
    )
    assert result == {"ok": True, "message_id": "wamid.tpl123"}


@pytest.mark.asyncio
async def test_mark_read(monkeypatch, tmp_path):
    _connect(monkeypatch, tmp_path)
    result = await whatsapp_connector.mark_read(
        "wamid.incoming1", client=_fake_client(_wa_handler)
    )
    assert result == {"ok": True, "read": True}


@pytest.mark.asyncio
async def test_writes_without_token_fail(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    for result in (
        await whatsapp_connector.send_message("962788809843", "hi"),
        await whatsapp_connector.send_template("962788809843", "hello_world"),
        await whatsapp_connector.mark_read("wamid.incoming1"),
    ):
        assert not result["ok"]
        assert "not connected" in result["error"]


@pytest.mark.asyncio
async def test_send_without_phone_number_id_fails(monkeypatch, tmp_path):
    _fresh_vault(monkeypatch, tmp_path, whatsapp_connector, "wa.json")
    whatsapp_connector.save_token("fake-wa-token")
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    result = await whatsapp_connector.send_message(
        "962788809843", "hi", client=_fake_client(_wa_handler)
    )
    assert not result["ok"]
    assert "not connected" in result["error"]


# --------------------------------------------------------------------
# Tools: registration + risk tiers
# --------------------------------------------------------------------

def test_connector_tools_registered_with_right_tiers():
    # Importing the plugin module registers the tools; the @tool
    # decorator returns each Tool, so these names ARE the registry
    # entries — no order dependence on other test files.
    from plugins.whatsapp_connector.plugin import (
        whatsapp_send_message,
        whatsapp_send_template,
        whatsapp_status,
    )

    registry = get_registry()
    # Sends: external changes, approval gate.
    for tool_obj in (whatsapp_send_message, whatsapp_send_template):
        assert registry.get(tool_obj.name) is tool_obj
        assert tool_obj.risk_tier == RiskTier.TIER_4_EXTERNAL, tool_obj.name
    # Status: observe only.
    assert registry.get(whatsapp_status.name) is whatsapp_status
    assert whatsapp_status.risk_tier == RiskTier.TIER_0_OBSERVE
