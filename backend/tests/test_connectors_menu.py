# ====================================================================
# JARVIS OMEGA — /connectors menu + Gmail / Calendar / Drive /
# WhatsApp / X / TikTok Telegram commands (2026-11-11)
# ====================================================================
"""
Tests for the /connectors menu and the second-wave connector commands.
The menu lets Sir pick any connector by number; for cookie connectors
he then chooses browser sign-in (dashboard link) or paste-cookies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import router_telegram
from backend.services import (
    dm_store,
    google_connector,
    tiktok_connector,
    whatsapp_connector,
    x_connector,
)
from backend.services.credentials_vault import CredentialsVault


def _fresh_vault(monkeypatch, tmp_path, module, name: str):
    vault = CredentialsVault(storage_path=str(tmp_path / name))
    vault.initialize()
    monkeypatch.setattr(module, "credentials_vault", vault)
    return vault


def _telegram_app():
    test_app = FastAPI()
    test_app.include_router(router_telegram.router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


def _prep(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    for module, name in (
        (google_connector, "g.json"),
        (whatsapp_connector, "w.json"),
        (x_connector, "x.json"),
        (tiktok_connector, "t.json"),
    ):
        _fresh_vault(monkeypatch, tmp_path, module, name)


def _responder():
    fake = MagicMock()
    fake.get_pending_draft.return_value = None
    return fake


def _not_connected():
    return {
        "github": AsyncMock(return_value={"connected": False}),
        "vercel": AsyncMock(return_value={"connected": False}),
        "google": AsyncMock(return_value={"connected": False}),
        "whatsapp": AsyncMock(return_value={"connected": False}),
        "x": AsyncMock(return_value={"connected": False}),
        "tiktok": AsyncMock(return_value={"connected": False}),
    }


def _patch_statuses(monkeypatch, mapping):
    from backend.services import (
        github_connector,
        vercel_connector,
    )

    monkeypatch.setattr(github_connector, "status", mapping["github"])
    monkeypatch.setattr(vercel_connector, "status", mapping["vercel"])
    monkeypatch.setattr(google_connector, "status", mapping["google"])
    monkeypatch.setattr(whatsapp_connector, "status", mapping["whatsapp"])
    monkeypatch.setattr(x_connector, "status", mapping["x"])
    monkeypatch.setattr(tiktok_connector, "status", mapping["tiktok"])


@pytest.mark.asyncio
async def test_connectors_menu_lists_all(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    _patch_statuses(monkeypatch, _not_connected())
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.dm_auth.connector_status",
              return_value={"connected": False}),
    ):
        assert _webhook_post("/connectors", update_id=1).status_code == 200
    reply = mock_send.call_args.args[0]
    for name in (
        "Instagram", "Messenger", "GitHub", "Vercel", "Google",
        "WhatsApp", "X", "TikTok",
    ):
        assert name in reply, name
    assert "not connected" in reply
    assert "111" in router_telegram._pending_connectors


@pytest.mark.asyncio
async def test_menu_pick_instagram_browser_then_paste(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    _patch_statuses(monkeypatch, _not_connected())
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.dm_auth.connector_status",
              return_value={"connected": False}),
    ):
        assert _webhook_post("/connectors", update_id=1).status_code == 200
        assert _webhook_post("1", update_id=2).status_code == 200
    reply = mock_send.call_args.args[0]
    assert "cookies" in reply
    assert "1. Open in browser" in reply
    assert "2. Paste cookies" in reply
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("1", update_id=3).status_code == 200
    reply = mock_send.call_args.args[0]
    assert "jarvis-frontend-iota.vercel.app" in reply
    assert "الموصلات" in reply
    assert "111" not in router_telegram._pending_connectors
    # Paste path instead.
    router_telegram._pending_connectors["111"] = {
        "stage": "cookies", "service": "instagram",
    }
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("2", update_id=4).status_code == 200
    assert router_telegram._pending_connect.get("111") == "instagram"
    assert "cookies" in mock_send.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_menu_pick_github_arms_token_wait(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    _patch_statuses(monkeypatch, _not_connected())
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.dm_auth.connector_status",
              return_value={"connected": False}),
    ):
        assert _webhook_post("/connectors", update_id=1).status_code == 200
        assert _webhook_post("3", update_id=2).status_code == 200
    assert router_telegram._pending_token.get("111") == "github"
    assert "GitHub" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_menu_bad_number(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    _patch_statuses(monkeypatch, _not_connected())
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch("backend.services.dm_auth.connector_status",
              return_value={"connected": False}),
    ):
        assert _webhook_post("/connectors", update_id=1).status_code == 200
        assert _webhook_post("99", update_id=2).status_code == 200
    assert "isn't on the menu" in mock_send.call_args.args[0]
    assert "111" in router_telegram._pending_connectors


@pytest.mark.asyncio
async def test_connect_google_oauth_client_flow(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/connect google", update_id=1).status_code == 200
    assert router_telegram._pending_oauth_client.get("111") == "google"
    assert "OAuth client" in mock_send.call_args.args[0]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("fake-id fake-secret", update_id=2).status_code == 200
    reply = mock_send.call_args.args[0]
    assert "accounts.google.com" in reply
    assert "fake-secret" not in reply
    assert "111" not in router_telegram._pending_oauth_client
    assert google_connector.has_client()


@pytest.mark.asyncio
async def test_connect_whatsapp_two_step_flow(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/connect whatsapp", update_id=1).status_code == 200
    assert router_telegram._pending_whatsapp.get("111") == "token"
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            whatsapp_connector, "verify_token",
            new=AsyncMock(return_value={"account_id": "123"}),
        ),
    ):
        assert _webhook_post("fake-wa-token", update_id=2).status_code == 200
    assert router_telegram._pending_whatsapp.get("111") == "phone"
    assert "phone number id" in mock_send.call_args.args[0].lower()
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            whatsapp_connector, "status",
            new=AsyncMock(return_value={"connected": True}),
        ),
    ):
        assert _webhook_post("123456789", update_id=3).status_code == 200
    assert "Connected to WhatsApp" in mock_send.call_args.args[0]
    assert "111" not in router_telegram._pending_whatsapp
    assert whatsapp_connector.is_connected()


@pytest.mark.asyncio
async def test_connect_x_oauth_client_flow(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/connect x", update_id=1).status_code == 200
    assert router_telegram._pending_oauth_client.get("111") == "x"
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("fake-x-id fake-x-secret", update_id=2).status_code == 200
    reply = mock_send.call_args.args[0]
    assert "twitter.com/i/oauth2/authorize" in reply
    assert "fake-x-secret" not in reply


@pytest.mark.asyncio
async def test_disconnect_second_wave(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_client("id", "secret")
    google_connector.save_refresh_token("tok")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/disconnect google", update_id=1).status_code == 200
    assert "Disconnected Google" in mock_send.call_args.args[0]
    assert not google_connector.is_connected()
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/disconnect whatsapp", update_id=2).status_code == 200
    assert "isn't connected" in mock_send.call_args.args[0]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/disconnect x", update_id=3).status_code == 200
    assert "isn't connected" in mock_send.call_args.args[0]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
    ):
        assert _webhook_post("/disconnect tiktok", update_id=4).status_code == 200
    assert "isn't connected" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_second_wave_commands_not_connected(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    for i, (cmd, needle) in enumerate((
        ("/gmail", "isn't connected"),
        ("/calendar", "isn't connected"),
        ("/drive", "isn't connected"),
        ("/whatsapp", "isn't connected"),
        ("/x", "isn't connected"),
        ("/tiktok", "isn't connected"),
    )):
        with (
            patch("backend.routers.router_telegram.send_telegram_message",
                  new=AsyncMock(return_value=True)) as mock_send,
            patch("backend.services.dm_responder.dm_responder", _responder()),
        ):
            assert _webhook_post(cmd, update_id=i + 1).status_code == 200
        assert needle in mock_send.call_args.args[0], cmd


@pytest.mark.asyncio
async def test_gmail_calendar_drive_connected(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    google_connector.save_refresh_token("fake-refresh")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            google_connector, "list_messages",
            new=AsyncMock(return_value={"ok": True, "messages": [
                {"id": "m1"}, {"id": "m2"},
            ]}),
        ),
        patch.object(
            google_connector, "get_message",
            new=AsyncMock(return_value={
                "ok": True, "id": "m1", "subject": "Test",
                "from": "omar@example.com",
            }),
        ),
    ):
        assert _webhook_post("/gmail", update_id=1).status_code == 200
    assert "Test" in mock_send.call_args.args[0]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            google_connector, "list_events",
            new=AsyncMock(return_value={"ok": True, "events": [
                {"summary": "Football", "start": "17:00", "end": "18:00"},
            ]}),
        ),
    ):
        assert _webhook_post("/calendar", update_id=2).status_code == 200
    assert "Football" in mock_send.call_args.args[0]
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            google_connector, "list_files",
            new=AsyncMock(return_value={"ok": True, "files": [
                {"name": "notes.pdf", "mimeType": "application/pdf"},
            ]}),
        ),
    ):
        assert _webhook_post("/drive", update_id=3).status_code == 200
    assert "notes.pdf" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_whatsapp_x_tiktok_commands_connected(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    whatsapp_connector.save_token("fake-wa-token")
    whatsapp_connector.save_phone_number_id("123")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            whatsapp_connector, "send_message",
            new=AsyncMock(return_value={"ok": True, "id": "wamid.1"}),
        ),
    ):
        assert _webhook_post(
            "/whatsapp send +962788809843 | hello", update_id=1
        ).status_code == 200
    assert "Sent to +962788809843" in mock_send.call_args.args[0]
    x_connector.save_tokens("fake-x-access", "fake-x-refresh")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            x_connector, "list_dm_conversations",
            new=AsyncMock(return_value={"ok": True, "conversations": [
                {"id": "c1", "last_message": "hey sir"},
            ]}),
        ),
    ):
        assert _webhook_post("/x", update_id=2).status_code == 200
    assert "c1" in mock_send.call_args.args[0]
    tiktok_connector.save_client_credentials("fake-key", "fake-secret")
    tiktok_connector._save_tokens("fake-tk-access", "fake-tk-refresh", "fake-open-id")
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", _responder()),
        patch.object(
            tiktok_connector, "list_conversations",
            new=AsyncMock(return_value={"ok": True, "conversations": [
                {"conversation_id": "t1"},
            ]}),
        ),
    ):
        assert _webhook_post("/tiktok", update_id=3).status_code == 200
    assert "t1" in mock_send.call_args.args[0]


# --------------------------------------------------------------------
# OAuth callbacks for X and TikTok
# --------------------------------------------------------------------

def test_x_oauth_callback_success(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from backend.routers.router_oauth import router, store_oauth_state

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    store_oauth_state("state-1", "x", {"code_verifier": "fake-verifier"})
    with patch.object(
        x_connector, "exchange_code",
        new=AsyncMock(return_value={"ok": True, "username": "rayan"}),
    ):
        resp = client.get("/api/oauth/x/callback?code=fake-code&state=state-1")
    assert resp.status_code == 200
    assert "X connected" in resp.text
    assert "@rayan" in resp.text


def test_x_oauth_callback_missing_state(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from backend.routers.router_oauth import router

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    resp = client.get("/api/oauth/x/callback?code=fake-code&state=nope")
    assert resp.status_code == 200
    assert "failed" in resp.text


def test_tiktok_oauth_callback_success(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from backend.routers.router_oauth import router

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    with patch.object(
        tiktok_connector, "exchange_code",
        new=AsyncMock(return_value={"ok": True, "display_name": "Rayyan"}),
    ):
        resp = client.get("/api/oauth/tiktok/callback?code=fake-code")
    assert resp.status_code == 200
    assert "TikTok connected" in resp.text
    assert "Rayyan" in resp.text


def test_tiktok_oauth_callback_error(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from backend.routers.router_oauth import router

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    resp = client.get("/api/oauth/tiktok/callback?error=access_denied")
    assert resp.status_code == 200
    assert "failed" in resp.text
