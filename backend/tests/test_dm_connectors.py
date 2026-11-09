# ====================================================================
# JARVIS OMEGA — DM Connectors tests
# ====================================================================
"""
Tests for the DM Connectors feature (Messenger + Instagram).

ALL credentials here are FAKE (e.g. "fake-user@example.com",
"fake-cookies"). No real login is ever attempted: platform HTTP calls
run through httpx.MockTransport, and the router tests monkeypatch the
verification functions. A "connected" result in these tests means the
code path worked against a mocked platform, not that any real account
was touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.router_connectors import router as connectors_router
from backend.services import dm_auth
from backend.services.credentials_vault import CredentialsVault
from backend.services.dm_llm import generate_dm_reply
from backend.services.dm_responder import DMResponder

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

FAKE_COOKIES = {"c_user": "111111", "xs": "fake-xs-value", "sessionid": "fake-session"}


@pytest.fixture()
def tmp_vault(tmp_path, monkeypatch):
    """Point the connector vault at a temp file for the test."""
    vault = CredentialsVault(storage_path=str(tmp_path / "connectors.json"))
    vault.initialize()
    monkeypatch.setattr(dm_auth, "connector_vault", vault)
    return vault


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------
# Cookie parsing
# --------------------------------------------------------------------

def test_parse_cookies_header_form():
    out = dm_auth.parse_cookies("c_user=111; xs=abc123; sessionid=xyz")
    assert out == {"c_user": "111", "xs": "abc123", "sessionid": "xyz"}


def test_parse_cookies_netscape_form():
    raw = (
        "# Netscape HTTP Cookie File\n"
        ".facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t111\n"
        ".facebook.com\tTRUE\t/\tTRUE\t0\txs\tabc\n"
    )
    assert dm_auth.parse_cookies(raw) == {"c_user": "111", "xs": "abc"}


def test_parse_cookies_json_forms():
    assert dm_auth.parse_cookies('{"sessionid": "s1", "ds_user_id": "9"}') == {
        "sessionid": "s1", "ds_user_id": "9",
    }
    assert dm_auth.parse_cookies('[{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]') == {
        "a": "1", "b": "2",
    }


def test_parse_cookies_garbage_raises():
    with pytest.raises(ValueError):
        dm_auth.parse_cookies("")
    with pytest.raises(ValueError):
        dm_auth.parse_cookies("not cookies at all {{{")


def test_parse_cookies_json_array_full_fields():
    # EditThisCookie / Chrome export shape, with metadata kept.
    raw = json.dumps([
        {"name": "c_user", "value": "111", "domain": ".facebook.com",
         "path": "/", "secure": True, "httpOnly": True, "hostOnly": False,
         "session": True, "expirationDate": 9999999999, "storeId": "0"},
        {"name": "xs", "value": "abc", "domain": ".facebook.com",
         "path": "/", "secure": True, "httpOnly": True},
        {"name": "sb", "value": "xyz", "host": ".facebook.com"},
    ])
    assert dm_auth.parse_cookies(raw) == {"c_user": "111", "xs": "abc", "sb": "xyz"}
    entries = dm_auth.parse_cookie_entries(raw)
    assert entries[0]["domain"] == ".facebook.com"
    assert entries[0]["path"] == "/"
    assert entries[0]["secure"] is True
    assert entries[0]["httpOnly"] is True
    assert entries[2]["domain"] == ".facebook.com"  # "host" alias


def test_parse_cookies_json_object_and_wrapper():
    assert dm_auth.parse_cookies('{"c_user": "111", "xs": "abc"}') == {
        "c_user": "111", "xs": "abc",
    }
    # {"cookies": [...]} wrapper some exporters use.
    assert dm_auth.parse_cookies(
        '{"cookies": [{"name": "sessionid", "value": "s1"}]}'
    ) == {"sessionid": "s1"}


def test_parse_cookies_stringified_json():
    # The paste itself is a JSON string holding JSON (double-encoded).
    inner = json.dumps([{"name": "c_user", "value": "111"}, {"name": "xs", "value": "abc"}])
    assert dm_auth.parse_cookies(json.dumps(inner)) == {"c_user": "111", "xs": "abc"}
    assert dm_auth.parse_cookies(json.dumps('{"sessionid": "s1"}')) == {"sessionid": "s1"}


def test_parse_cookies_netscape_httponly_lines():
    raw = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t111\n"
        ".facebook.com\tTRUE\t/\tTRUE\t0\txs\tabc\n"
    )
    assert dm_auth.parse_cookies(raw) == {"c_user": "111", "xs": "abc"}
    entries = dm_auth.parse_cookie_entries(raw)
    assert entries[0]["httpOnly"] is True
    assert entries[0]["domain"] == ".facebook.com"
    assert "httpOnly" not in entries[1]


def test_parse_cookies_duplicates_last_wins():
    assert dm_auth.parse_cookies("c_user=1; c_user=2") == {"c_user": "2"}
    assert dm_auth.parse_cookies(
        '[{"name": "xs", "value": "old"}, {"name": "xs", "value": "new"}]'
    ) == {"xs": "new"}


def test_parse_cookies_set_cookie_attributes_ignored():
    # A pasted Set-Cookie line must not turn Path/Domain/Secure into cookies.
    out = dm_auth.parse_cookies(
        "c_user=111; Path=/; Domain=.facebook.com; Secure; HttpOnly; SameSite=None"
    )
    assert out == {"c_user": "111"}


def test_parse_cookies_invalid_json_names_the_problem():
    with pytest.raises(ValueError, match="JSON"):
        dm_auth.parse_cookies('{"c_user": "111",}')
    with pytest.raises(ValueError, match="no usable"):
        dm_auth.parse_cookies("[]")
    with pytest.raises(ValueError, match="no usable"):
        dm_auth.parse_cookies('[{"name": "only-name"}]')


def test_parse_cookies_malformed_json_salvages_pairs():
    # A paste with a broken quote (e.g. a missing quote on a domain line)
    # still yields every name/value pair instead of a hard error.
    raw = json.dumps([
        {"name": "c_user", "value": "111", "domain": ".instagram.com",
         "path": "/", "secure": True, "httpOnly": True},
        {"name": "xs", "value": "abc", "domain": ".instagram.com"},
        {"name": "sessionid", "value": "s1", "domain": ".instagram.com"},
    ], indent=2)
    broken = raw.replace('"domain": ".instagram.com",', 'domain": ".instagram.com",', 1)
    assert dm_auth.parse_cookies(broken) == {
        "c_user": "111", "xs": "abc", "sessionid": "s1",
    }


def test_parse_cookies_truncated_json_salvages_complete_pairs():
    # A paste cut off mid-file yields the pairs that are complete.
    raw = json.dumps([
        {"name": "c_user", "value": "111"},
        {"name": "xs", "value": "abc"},
        {"name": "sessionid", "value": "s1"},
    ], indent=2)
    assert dm_auth.parse_cookies(raw.split('"sessionid"')[0]) == {
        "c_user": "111", "xs": "abc",
    }
    # Pure garbage with no name/value pairs still raises.
    with pytest.raises(ValueError, match="JSON"):
        dm_auth.parse_cookies('[{not json at all')


# --------------------------------------------------------------------
# Vault round-trip (encrypted at rest)
# --------------------------------------------------------------------

def test_connector_vault_round_trip(tmp_vault):
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    blob = dm_auth.load_connector("messenger")
    assert blob is not None
    assert blob["method"] == "cookies"
    assert blob["data"]["cookies"] == FAKE_COOKIES
    # The file on disk must not contain the plaintext cookie values.
    raw_file = Path(tmp_vault._path).read_text(encoding="utf-8")
    assert "fake-xs-value" not in raw_file
    assert "fake-session" not in raw_file
    # Status exposes no secrets.
    status = dm_auth.connector_status("messenger")
    assert status["connected"] is True
    assert status["auth_method"] == "cookies"
    assert "fake-xs-value" not in json.dumps(status)
    assert dm_auth.delete_connector("messenger") is True
    assert dm_auth.connector_status("messenger")["connected"] is False


# --------------------------------------------------------------------
# Session probe (mocked platform HTTP)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_cookies_messenger_logged_in():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Messenger app shell</html>", request=request)

    assert await dm_auth.verify_cookies(
        "messenger", FAKE_COOKIES, transport=httpx.MockTransport(handler)
    ) is True


@pytest.mark.asyncio
async def test_verify_cookies_messenger_redirects_to_login():
    def handler(request: httpx.Request) -> httpx.Response:
        if "messenger.com" in str(request.url):
            return httpx.Response(
                302, headers={"Location": "https://www.facebook.com/login/"}, request=request
            )
        return httpx.Response(200, text="login page", request=request)

    assert await dm_auth.verify_cookies(
        "messenger", {"c_user": "bad"}, transport=httpx.MockTransport(handler)
    ) is False


@pytest.mark.asyncio
async def test_verify_cookies_instagram_logged_in():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='{"config": {"viewer": {"id": "9"}}, "ds_user_id": "9"}', request=request
        )

    assert await dm_auth.verify_cookies(
        "instagram", {"sessionid": "fake"}, transport=httpx.MockTransport(handler)
    ) is True


# --------------------------------------------------------------------
# Messenger password login (mocked Facebook login flow)
# --------------------------------------------------------------------

def _fb_login_handler(success: str):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "GET" and url == "https://www.facebook.com/login/":
            html = (
                '<form action="/login/device-based/regular/login/">'
                '<input name="lsd" value="LSD123">'
                '<input name="jazoest" value="JZ456">'
                '<input name="m_ts" value="MTS789">'
                '<input name="li" value="LI000">'
                "</form>"
            )
            return httpx.Response(200, text=html, request=request)
        if request.method == "POST" and "regular/login" in url:
            if success == "ok":
                return httpx.Response(
                    302,
                    headers={
                        "Location": "https://www.facebook.com/",
                        "Set-Cookie": "c_user=111111; Path=/",
                    },
                    request=request,
                )
            if success == "checkpoint":
                return httpx.Response(
                    302,
                    headers={"Location": "https://www.facebook.com/checkpoint/"},
                    request=request,
                )
            return httpx.Response(
                302,
                headers={"Location": "https://www.facebook.com/login/"},
                request=request,
            )
        if url == "https://www.facebook.com/":
            return httpx.Response(200, text="home", request=request)
        return httpx.Response(200, text="login page", request=request)

    return handler


@pytest.mark.asyncio
async def test_messenger_password_login_success():
    cookies = await dm_auth.login_with_password(
        "messenger", "fake-user@example.com", "fake-password",
        transport=httpx.MockTransport(_fb_login_handler("ok")),
    )
    assert cookies.get("c_user") == "111111"


@pytest.mark.asyncio
async def test_messenger_password_login_bad_password():
    with pytest.raises(dm_auth.LoginFailed):
        await dm_auth.login_with_password(
            "messenger", "fake-user@example.com", "wrong-password",
            transport=httpx.MockTransport(_fb_login_handler("bad")),
        )


@pytest.mark.asyncio
async def test_messenger_password_login_checkpoint():
    with pytest.raises(dm_auth.LoginChallenge):
        await dm_auth.login_with_password(
            "messenger", "fake-user@example.com", "fake-password",
            transport=httpx.MockTransport(_fb_login_handler("checkpoint")),
        )


# --------------------------------------------------------------------
# Router: validation + store flow (verification monkeypatched)
# --------------------------------------------------------------------

@pytest.fixture()
def api_client(tmp_vault):
    app = FastAPI()
    app.include_router(connectors_router)
    with TestClient(app) as client:
        yield client


def test_list_connectors_disconnected(api_client):
    resp = api_client.get("/api/connectors")
    assert resp.status_code == 200
    data = resp.json()
    ids = {c["id"] for c in data["connectors"]}
    assert ids == {"messenger", "instagram"}
    assert all(c["connected"] is False for c in data["connectors"])
    assert "fake" not in resp.text


def test_connect_rejects_unknown_platform(api_client):
    resp = api_client.post("/api/connectors/whatsapp/connect", json={"method": "cookies", "cookies": "a=b"})
    assert resp.status_code == 404


def test_connect_rejects_empty_body(api_client):
    resp = api_client.post("/api/connectors/messenger/connect", json={})
    assert resp.status_code == 422


def test_connect_rejects_both_forms(api_client):
    resp = api_client.post("/api/connectors/messenger/connect", json={
        "method": "cookies", "cookies": "c_user=1",
        "email": "a@b.c", "password": "x",
    })
    assert resp.status_code == 422


def test_connect_rejects_password_without_password(api_client):
    resp = api_client.post("/api/connectors/instagram/connect", json={
        "method": "password", "email": "fake@example.com",
    })
    assert resp.status_code == 422


def test_connect_cookies_success_stores_nothing_secret_in_response(api_client, monkeypatch):
    async def fake_verify(platform, cookies, transport=None):
        return True

    monkeypatch.setattr(dm_auth, "verify_cookies", fake_verify)
    resp = api_client.post("/api/connectors/messenger/connect", json={
        "method": "cookies", "cookies": "c_user=111; xs=fake-xs-value",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["auth_method"] == "cookies"
    assert "fake-xs-value" not in resp.text
    assert "xs" not in resp.text
    assert dm_auth.connector_status("messenger")["connected"] is True


def test_connect_cookies_failed_verification_stores_nothing(api_client, monkeypatch):
    async def fake_verify(platform, cookies, transport=None):
        return False

    monkeypatch.setattr(dm_auth, "verify_cookies", fake_verify)
    resp = api_client.post("/api/connectors/messenger/connect", json={
        "method": "cookies", "cookies": "c_user=bad",
    })
    assert resp.status_code == 502
    assert dm_auth.connector_status("messenger")["connected"] is False


def test_connect_password_challenge_stores_nothing(api_client, monkeypatch):
    async def fake_login(platform, email, password, transport=None):
        raise dm_auth.LoginChallenge("verification code required")

    monkeypatch.setattr(dm_auth, "login_with_password", fake_login)
    resp = api_client.post("/api/connectors/instagram/connect", json={
        "method": "password", "email": "fake@example.com", "password": "fake-pass",
    })
    assert resp.status_code == 428
    assert dm_auth.connector_status("instagram")["connected"] is False


def test_disconnect(api_client, monkeypatch):
    async def fake_verify(platform, cookies, transport=None):
        return True

    monkeypatch.setattr(dm_auth, "verify_cookies", fake_verify)
    assert api_client.post("/api/connectors/instagram/connect", json={
        "method": "cookies", "cookies": "sessionid=fake",
    }).status_code == 200
    resp = api_client.post("/api/connectors/instagram/disconnect")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False
    assert api_client.post("/api/connectors/instagram/disconnect").status_code == 404


# --------------------------------------------------------------------
# DM LLM: Groq primary, Gemini fallback (mocked HTTP)
# --------------------------------------------------------------------

def _groq_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": "أهلاً! كيف أقدر أساعدك؟"}}],
    }, request=request)


def _gemini_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": "مرحباً!"}]}}],
    }, request=request)


@pytest.mark.asyncio
async def test_dm_llm_groq_primary(monkeypatch):
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr("backend.services.dm_llm.settings.gemini_api_key", "fake-gemini-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_groq_ok)) as client:
        result = await generate_dm_reply("messenger", "Friend", "مرحبا", client=client)
    assert result["ok"] is True
    assert result["model"] == "groq"
    assert "أهلاً" in result["reply"]


@pytest.mark.asyncio
async def test_dm_llm_falls_back_to_gemini(monkeypatch):
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr("backend.services.dm_llm.settings.gemini_api_key", "fake-gemini-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if "groq" in str(request.url):
            return httpx.Response(429, json={"error": {"message": "rate limited"}}, request=request)
        return _gemini_ok(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await generate_dm_reply("instagram", "Friend", "hi", client=client)
    assert result["ok"] is True
    assert result["model"] == "gemini"
    assert result["reply"] == "مرحباً!"


@pytest.mark.asyncio
async def test_dm_llm_both_fail(monkeypatch):
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr("backend.services.dm_llm.settings.gemini_api_key", "fake-gemini-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await generate_dm_reply("messenger", "Friend", "hi", client=client)
    assert result["ok"] is False


# --------------------------------------------------------------------
# Responder: one poll cycle with fake platform clients
# --------------------------------------------------------------------

class _FakeClient:
    def __init__(self, user_id, messages):
        self.user_id = user_id
        self._messages = messages
        self.sent = []

    async def validate(self):
        return True

    async def list_recent(self, limit=10):
        return self._messages

    async def send(self, thread_id, text):
        self.sent.append((thread_id, text))
        return {"ok": True, "message_id": "sent-1"}


def _msg(platform, thread_id, sender_id, sender_name, text, message_id, is_group=False):
    return {
        "platform": platform, "thread_id": thread_id, "sender_id": sender_id,
        "sender_name": sender_name, "text": text, "message_id": message_id,
        "is_group": is_group,
    }


@pytest.mark.asyncio
async def test_responder_replies_once_then_skips_seen(tmp_vault, tmp_path, monkeypatch):
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [
        _msg("messenger", "t1", "999", "Friend", "مرحبا", "m1"),
        _msg("messenger", "t2", "111111", "Me", "my own msg", "m2"),  # own message: skip
        _msg("messenger", "t3", "888", "Group", "hi all", "m3", is_group=True),  # group: skip
    ]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None):
        return {"ok": True, "reply": "أهلاً!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )

    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert fake.sent == [("t1", "أهلاً!")]
    # Second poll: the same message is now seen, so nothing is sent again.
    result2 = await responder.poll_once()
    assert result2["messenger"]["replied"] == 0
    assert len(fake.sent) == 1
