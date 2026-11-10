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
from datetime import UTC, datetime, timedelta
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


def _msg(platform, thread_id, sender_id, sender_name, text, message_id, is_group=False, is_missed_call=False):
    return {
        "platform": platform, "thread_id": thread_id, "sender_id": sender_id,
        "sender_name": sender_name, "text": text, "message_id": message_id,
        "is_group": is_group, "is_missed_call": is_missed_call,
    }


@pytest.mark.asyncio
async def test_responder_waits_one_minute_then_replies_once(tmp_vault, tmp_path, monkeypatch):
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [
        _msg("messenger", "t1", "999", "Friend", "مرحبا", "m1"),
        _msg("messenger", "t2", "111111", "Me", "my own msg", "m2"),  # own message: skip
        _msg("messenger", "t3", "888", "Group", "hi all", "m3", is_group=True),  # group: skip
    ]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    seen_first_reply = []

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        seen_first_reply.append(first_reply)
        return {"ok": True, "reply": "أهلاً!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )

    # First poll: the message is new, so Jarvis records it and waits out
    # the one-minute rule instead of replying immediately.
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    # A second poll inside the minute still waits.
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    # Once a minute has passed since it was first seen, it replies —
    # with the intro (first reply in this thread).
    responder._pending["messenger"]["t1"]["first_seen"] = (
        datetime.now(UTC) - timedelta(seconds=61)
    ).isoformat()
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert fake.sent == [("t1", "أهلاً!")]
    assert seen_first_reply == [True]
    # Third poll: the same message is now seen, so nothing is sent again.
    result2 = await responder.poll_once()
    assert result2["messenger"]["replied"] == 0
    assert len(fake.sent) == 1


@pytest.mark.asyncio
async def test_responder_follow_up_replies_without_wait(tmp_vault, tmp_path, monkeypatch):
    """Once Jarvis introduced itself, follow-ups keep the back-and-forth going."""
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    fake = _FakeClient(user_id="111111", messages=[
        _msg("messenger", "t1", "999", "Friend", "مرحبا", "m1"),
    ])
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    seen_first_reply = []

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        seen_first_reply.append(first_reply)
        return {"ok": True, "reply": "أهلاً!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )

    # Intro reply (after the minute).
    await responder.poll_once()
    responder._pending["messenger"]["t1"]["first_seen"] = (
        datetime.now(UTC) - timedelta(seconds=61)
    ).isoformat()
    await responder.poll_once()
    assert len(fake.sent) == 1
    assert seen_first_reply == [True]
    # The friend writes back: a new message id in the same thread.
    # Jarvis replies on the next poll, without another minute's wait,
    # and with the follow-up prompt (no re-introduction).
    fake._messages = [_msg("messenger", "t1", "999", "Friend", "تمام، شكراً", "m2")]
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert len(fake.sent) == 2
    assert seen_first_reply == [True, False]


@pytest.mark.asyncio
async def test_responder_stands_down_when_sir_replies(tmp_vault, tmp_path, monkeypatch):
    """If Sir answers the thread himself inside the minute, Jarvis never replies."""
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    fake = _FakeClient(user_id="111111", messages=[
        _msg("messenger", "t1", "999", "Friend", "مرحبا", "m1"),
    ])
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "أهلاً!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )

    await responder.poll_once()
    assert responder._pending["messenger"]["t1"]["message_id"] == "m1"
    # Sir replies himself before the minute is up.
    fake._messages = [_msg("messenger", "t1", "111111", "Me", "هلا", "m2")]
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    assert responder._pending.get("messenger", {}).get("t1") is None


@pytest.mark.asyncio
async def test_dm_llm_intro_vs_follow_up_prompt(monkeypatch):
    """First reply introduces Jarvis + busy; follow-up keeps going, no re-intro."""
    monkeypatch.setattr("backend.services.dm_llm.settings.groq_api_key", "fake-groq-key")
    monkeypatch.setattr("backend.services.dm_llm.settings.gemini_api_key", "fake-gemini-key")
    seen_prompts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen_prompts.append(body["messages"][0]["content"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "أهلاً! أنا جارفيس."}}],
        }, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await generate_dm_reply("messenger", "Friend", "مرحبا", client=client, first_reply=True)
        follow = await generate_dm_reply("messenger", "Friend", "تمام", client=client, first_reply=False)
    assert first["ok"] is True and follow["ok"] is True
    assert "introduce yourself briefly as Jarvis" in seen_prompts[0]
    assert "busy right now" in seen_prompts[0]
    assert "make sure Rayyan sees it" in seen_prompts[0]
    assert "already introduced yourself as Jarvis" in seen_prompts[1]
    assert "do not introduce yourself again" in seen_prompts[1]


# --------------------------------------------------------------------
# Instagram full-settings session (instagrapi documented flow)
# --------------------------------------------------------------------
# A browser/web sessionid is rejected by Instagram's private mobile API
# with login_required, so the responder must restore the FULL session
# (dump_settings -> set_settings) from a password login instead of
# relying on login_by_sessionid(). These tests use a fake instagrapi
# module injected into sys.modules (the real library is not installed
# in the test venv); all values are fake.

import sys as _sys
import types as _types
from typing import Any


def _fake_instagrapi(monkeypatch):
    """Inject a fake instagrapi module; returns the recorded calls."""
    calls: dict[str, Any] = {"set_settings": [], "login_by_sessionid": [], "login": []}

    class FakeClient:
        def __init__(self):
            self.private = _types.SimpleNamespace(
                cookies={"sessionid": "fake-session", "ds_user_id": "51500959582",
                         "csrftoken": "fake-csrf", "mid": "fake-mid", "ig_did": "fake-did"}
            )

        def set_settings(self, settings):
            calls["set_settings"].append(settings)

        def login_by_sessionid(self, sessionid):
            calls["login_by_sessionid"].append(sessionid)

        def login(self, username, password):
            calls["login"].append((username, password))

        def dump_settings(self):
            return {"uuids": {"uuid": "fake-uuid"}, "authorization_data": {"sessionid": "fake-session"}}

        def get_timeline_feed(self, amount=1):
            return []

        def account_info(self):
            return _types.SimpleNamespace(pk=51500959582)

    fake_mod = _types.ModuleType("instagrapi")
    fake_mod.Client = FakeClient
    fake_exc = _types.ModuleType("instagrapi.exceptions")

    class _Err(Exception):
        pass

    fake_exc.BadPassword = _Err
    fake_exc.ChallengeRequired = _Err
    fake_exc.TwoFactorRequired = _Err
    fake_mod.exceptions = fake_exc
    monkeypatch.setitem(_sys.modules, "instagrapi", fake_mod)
    monkeypatch.setitem(_sys.modules, "instagrapi.exceptions", fake_exc)
    return calls


def test_instagram_client_prefers_full_settings(monkeypatch):
    """With full settings, the client restores via set_settings, never login_by_sessionid."""
    from backend.services.dm_clients import InstagramClient

    calls = _fake_instagrapi(monkeypatch)
    settings = {"uuids": {"uuid": "fake-uuid"}, "authorization_data": {"sessionid": "fake-session"}}
    client = InstagramClient(session_cookies={"sessionid": "fake-session"}, settings=settings)
    client._require_client()
    assert calls["set_settings"] == [settings]
    assert calls["login_by_sessionid"] == []
    assert client.validate() is True


def test_instagram_client_cookies_only_falls_back_to_sessionid(monkeypatch):
    """Without settings, the client still falls back to login_by_sessionid."""
    from backend.services.dm_clients import InstagramClient

    calls = _fake_instagrapi(monkeypatch)
    client = InstagramClient(session_cookies={"sessionid": "fake-session"})
    client._require_client()
    assert calls["login_by_sessionid"] == ["fake-session"]
    assert calls["set_settings"] == []


def test_instagram_password_login_returns_settings(monkeypatch):
    """A password login returns both cookies AND the full dump_settings()."""
    calls = _fake_instagrapi(monkeypatch)
    result = dm_auth._instagram_password_login("fake-user", "fake-pass")
    assert calls["login"] == [("fake-user", "fake-pass")]
    assert result["cookies"]["sessionid"] == "fake-session"
    assert result["settings"]["uuids"]["uuid"] == "fake-uuid"


def test_responder_build_client_passes_settings(monkeypatch):
    """The responder hands the stored settings to the Instagram client."""
    from backend.services.dm_clients import InstagramClient

    responder = DMResponder()
    settings = {"uuids": {"uuid": "fake-uuid"}}
    client = responder._build_client(
        "instagram", "password",
        {"cookies": {"sessionid": "fake-session"}, "settings": settings},
    )
    assert isinstance(client, InstagramClient)
    assert client._settings == settings


def test_instagram_validate_does_not_call_get_timeline_feed(monkeypatch):
    """Regression: validate() must not call get_timeline_feed(amount=...).

    instagrapi 3.2.8's get_timeline_feed takes no `amount` kwarg, so the
    old call raised TypeError on every poll and validate() wrongly
    reported the session as expired (the login itself succeeded).
    account_info() alone is the session check.
    """
    calls = _fake_instagrapi(monkeypatch)

    # The fake Client's get_timeline_feed must raise exactly like the real
    # 3.2.8 one does when passed an unexpected kwarg, so the test would
    # fail if validate() still called it with amount=.
    orig_client = _sys.modules["instagrapi"].Client

    class StrictClient(orig_client):
        def get_timeline_feed(self, *args, **kwargs):
            if "amount" in kwargs:
                raise TypeError(
                    "get_timeline_feed() got an unexpected keyword argument 'amount'"
                )
            return super().get_timeline_feed(*args, **kwargs)

    _sys.modules["instagrapi"].Client = StrictClient
    from backend.services.dm_clients import InstagramClient

    client = InstagramClient(session_cookies={"sessionid": "fake-session"})
    assert client.validate() is True
    # login_by_sessionid ran (session restore), get_timeline_feed(amount=) never did.
    assert calls["login_by_sessionid"] == ["fake-session"]


# --------------------------------------------------------------------
# DM introduce: chat-triggered introduction to the last unseen thread
# --------------------------------------------------------------------

def _fake_dm_client(monkeypatch, threads, user_id="999"):
    """A fake platform client for introduce_latest tests."""
    sent: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self):
            self.user_id = user_id

        def validate(self):
            return True

        async def list_recent(self, limit=10):
            return list(threads)

        async def send(self, thread_id, text):
            sent.append((thread_id, text))
            return {"ok": True, "message_id": "m-sent"}

    return FakeClient(), sent


@pytest.mark.asyncio
async def test_introduce_latest_sends_to_most_recent_unseen(tmp_path, monkeypatch):
    """introduce_latest sends the first-reply intro to the newest unseen thread."""
    import backend.services.dm_responder as dm_resp_mod
    from backend.services.dm_responder import DMResponder

    threads = [
        {"thread_id": "t-new", "sender_id": "111", "sender_name": "Sara",
         "text": "hi", "message_id": "m-new", "is_group": False},
        {"thread_id": "t-old", "sender_id": "222", "sender_name": "Omar",
         "text": "hey", "message_id": "m-old", "is_group": False},
    ]
    client, sent = _fake_dm_client(monkeypatch, threads)
    monkeypatch.setattr(dm_resp_mod.dm_auth, "load_connector",
                        lambda p: {"method": "cookies", "data": {"cookies": {"sessionid": "x"}}} if p == "instagram" else None)
    monkeypatch.setattr(DMResponder, "_build_client", lambda self, p, m, d: client)
    async def _fake_gen(*a, **k):
        return {"ok": True, "reply": "Hi, I'm Jarvis."}

    monkeypatch.setattr(dm_resp_mod, "generate_dm_reply", _fake_gen)
    # The module-level generate_dm_reply import in dm_responder is the one
    # introduce_latest calls; patch it on the module.
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    result = await responder.introduce_latest()
    assert result["ok"] is True
    assert result["platform"] == "instagram"
    assert result["sender_name"] == "Sara"
    assert result["thread_id"] == "t-new"
    assert sent == [("t-new", "Hi, I'm Jarvis.")]
    # Marked introduced so the poll loop will not duplicate it.
    assert responder._introduced["instagram"]["t-new"] is True


@pytest.mark.asyncio
async def test_introduce_latest_skips_own_and_introduced(tmp_path, monkeypatch):
    """Threads Sir answered himself or already introduced are skipped."""
    import backend.services.dm_responder as dm_resp_mod
    from backend.services.dm_responder import DMResponder

    threads = [
        {"thread_id": "t-mine", "sender_id": "999", "sender_name": "Rayyan",
         "text": "ok", "message_id": "m-mine", "is_group": False},
        {"thread_id": "t-done", "sender_id": "333", "sender_name": "Lina",
         "text": "hi", "message_id": "m-done", "is_group": False},
    ]
    client, sent = _fake_dm_client(monkeypatch, threads)
    monkeypatch.setattr(dm_resp_mod.dm_auth, "load_connector",
                        lambda p: {"method": "cookies", "data": {"cookies": {"sessionid": "x"}}} if p == "instagram" else None)
    monkeypatch.setattr(DMResponder, "_build_client", lambda self, p, m, d: client)
    async def _fake_gen(*a, **k):
        return {"ok": True, "reply": "Hi, I'm Jarvis."}

    monkeypatch.setattr(dm_resp_mod, "generate_dm_reply", _fake_gen)
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    responder._introduced = {"instagram": {"t-done": True}}
    result = await responder.introduce_latest()
    assert result["ok"] is False
    assert result["reason"] == "no_unseen"
    assert sent == []


@pytest.mark.asyncio
async def test_introduce_latest_no_connector(tmp_path, monkeypatch):
    """No connected account -> no_connector, nothing sent."""
    import backend.services.dm_responder as dm_resp_mod
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_resp_mod.dm_auth, "load_connector", lambda p: None)
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    result = await responder.introduce_latest()
    assert result == {"ok": False, "reason": "no_connector"}


def test_parse_introduce_request_matches():
    from backend.routers.router_chat import _parse_introduce_request

    assert _parse_introduce_request(
        "Introduce your self to the last one that messaged me and I haven't seen his message"
    ) is True
    assert _parse_introduce_request("introduce yourself to the last person who messaged me") is True
    assert _parse_introduce_request("عرف بنفسك لآخر شخص راسلني") is True
    assert _parse_introduce_request("قدم نفسك لآخر واحد بعتلي رسالة") is True


def test_parse_introduce_request_rejects():
    from backend.routers.router_chat import _parse_introduce_request

    assert _parse_introduce_request("introduce yourself") is False
    assert _parse_introduce_request("what is the weather") is False
    assert _parse_introduce_request("send a message to Sara") is False
    assert _parse_introduce_request("turn off the dm responder") is False


@pytest.mark.asyncio
async def test_catch_up_marks_existing_threads_seen_without_replying(tmp_path, monkeypatch):
    """On start, catch-up records all current threads as seen+introduced
    and sends NOTHING — so a fresh seen-state (wiped on redeploy) never
    makes the responder introduce itself to the whole old inbox."""
    import backend.services.dm_responder as dm_resp_mod
    from backend.services.dm_responder import DMResponder

    threads = [
        {"thread_id": "t1", "sender_id": "111", "sender_name": "Sara",
         "text": "hi", "message_id": "m1", "is_group": False},
        {"thread_id": "t2", "sender_id": "222", "sender_name": "Omar",
         "text": "hey", "message_id": "m2", "is_group": False},
    ]
    client, sent = _fake_dm_client(monkeypatch, threads)
    monkeypatch.setattr(dm_resp_mod.dm_auth, "load_connector",
                        lambda p: {"method": "cookies", "data": {"cookies": {"sessionid": "x"}}} if p == "instagram" else None)
    monkeypatch.setattr(DMResponder, "_build_client", lambda self, p, m, d: client)
    responder = DMResponder(seen_path=str(tmp_path / "seen.json"))
    await responder._catch_up()
    assert sent == []
    assert responder._seen["instagram"] == {"t1": "m1", "t2": "m2"}
    assert responder._introduced["instagram"] == {"t1": True, "t2": True}
    # A later introduce_latest now finds nothing new to introduce to.
    result = await responder.introduce_latest()
    assert result["ok"] is False
    assert result["reason"] == "no_unseen"
    assert sent == []


# --- New behaviours: group chats, web search, important alerts ---

@pytest.mark.asyncio
async def test_responder_replies_in_group_chat(tmp_vault, tmp_path, monkeypatch):
    """Group chats are answered too (not skipped): Jarvis addresses the
    sender by name and keeps it brief. The one-minute rule still applies."""
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [
        _msg("messenger", "g1", "999", "Friend", "hi everyone", "m1", is_group=True),
    ]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    seen_is_group = []

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        seen_is_group.append(is_group)
        return {"ok": True, "reply": "Hey Friend, this is Jarvis.", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )

    # First poll: new group message, waits out the minute.
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    # Fast-forward past the minute: the group message gets a reply.
    responder._pending["messenger"]["g1"]["first_seen"] = (
        datetime.now(UTC) - timedelta(seconds=61)
    ).isoformat()
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert len(fake.sent) == 1
    assert fake.sent[0][0] == "g1"
    assert seen_is_group == [True]


def test_is_important_detection():
    """_is_important flags English + Arabic importance markers."""
    from backend.services.dm_responder import _is_important

    assert _is_important("this is important, please tell Rayyan")
    assert _is_important("URGENT: call me back")
    assert _is_important("هذا مهم جدا")
    assert _is_important("ضروري ترد علي")
    assert _is_important("عاجل!")
    assert not _is_important("hi, how are you?")
    assert not _is_important("مرحبا كيفك")
    assert not _is_important("")


def test_looks_like_web_question():
    """_looks_like_web_question flags live-info questions only."""
    from backend.services.dm_llm import _looks_like_web_question

    assert _looks_like_web_question("what is the weather in Amman today?")
    assert _looks_like_web_question("who won the match last night?")
    assert _looks_like_web_question("ما هو الطقس اليوم؟")
    assert _looks_like_web_question("ابحث عن سعر الذهب")
    assert not _looks_like_web_question("hi, how are you?")
    assert not _looks_like_web_question("مرحبا كيفك")
    assert not _looks_like_web_question("thanks, talk later")


@pytest.mark.asyncio
async def test_maybe_web_context_skips_plain_chat(monkeypatch):
    """Plain chat never triggers a web search (no network call)."""
    from backend.services.dm_llm import _maybe_web_context

    assert await _maybe_web_context("hi, how are you?") == ""
    assert await _maybe_web_context("مرحبا كيفك") == ""


# --- Accuracy + completeness (DM reply quality) ---

def test_complete_reply():
    """_complete_reply never lets a half-finished message through."""
    from backend.services.dm_llm import _complete_reply

    # Already complete: returned as-is.
    assert _complete_reply("Hello, this is Jarvis.") == "Hello, this is Jarvis."
    assert _complete_reply("أهلاً! كيف حالك؟") == "أهلاً! كيف حالك؟"
    # Cut off mid-sentence: trimmed back to the last complete sentence.
    assert _complete_reply("Hi, I am Jarvis. Rayyan is busy and") == "Hi, I am Jarvis."
    assert _complete_reply("مرحبا. أنا جارفيس، وريان مشغول") == "مرحبا."
    # No complete sentence at all: None (caller falls back / skips).
    assert _complete_reply("Rayyan is busy and") is None
    assert _complete_reply("") is None
    assert _complete_reply("   ") is None
    # Ellipsis counts as finished.
    assert _complete_reply("Thinking about it...") == "Thinking about it..."


def test_dm_prompts_have_accuracy_rules():
    """Both DM prompts forbid inventing facts and half-finished messages."""
    from backend.services.dm_llm import (
        _SYSTEM_PROMPT_FIRST,
        _SYSTEM_PROMPT_FOLLOW_UP,
    )

    for prompt in (_SYSTEM_PROMPT_FIRST, _SYSTEM_PROMPT_FOLLOW_UP):
        assert "Never invent facts" in prompt
        assert "Always finish your sentences" in prompt
        assert "half-finished" in prompt


def test_looks_like_web_question_broadened():
    """The broadened triggers catch more factual questions."""
    from backend.services.dm_llm import _looks_like_web_question

    assert _looks_like_web_question("how much is the new iPhone?")
    assert _looks_like_web_question("how many goals did he score?")
    assert _looks_like_web_question("when did the match start?")
    assert _looks_like_web_question("كم سعر الذهب اليوم؟")
    # Plain chat still does not trigger a search.
    assert not _looks_like_web_question("hi, how are you?")
    assert not _looks_like_web_question("thanks, talk later")


# --- VIP contacts, tricky drafts, media, nudges, digest, send-to-name ---

def test_is_vip(monkeypatch):
    from backend.services.dm_responder import _is_vip

    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Mom, Dad, Layla")
    assert _is_vip("Mom") is True
    assert _is_vip("mom") is True
    assert _is_vip("Layla Haddad") is True
    assert _is_vip("Omar") is False
    assert _is_vip("") is False


def test_is_tricky():
    from backend.services.dm_responder import _is_tricky

    assert _is_tricky("can you send me money?") is True
    assert _is_tricky("what is the price?") is True
    assert _is_tricky("كم سعر الذهب؟") is True
    assert _is_tricky("hi, how are you?") is False
    assert _is_tricky("") is False


@pytest.mark.asyncio
async def test_vip_skips_one_minute_wait(tmp_vault, tmp_path, monkeypatch):
    """A VIP's first message is answered immediately, no one-minute wait."""
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Mom")
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Mom", "hello", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "Hi Mom!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert fake.sent == [("t1", "Hi Mom!")]


@pytest.mark.asyncio
async def test_photo_message_is_not_skipped(tmp_vault, tmp_path, monkeypatch):
    """A photo (no text, has media_url) is processed, not skipped."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [{
        "platform": "messenger", "thread_id": "t1", "sender_id": "999",
        "sender_name": "Friend", "text": "", "message_id": "m1",
        "is_group": False, "media_url": "https://cdn.example/p.jpg",
        "media_type": "photo",
    }]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)
    seen_media = {}

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        seen_media["media_url"] = media_url
        seen_media["media_type"] = media_type
        return {"ok": True, "reply": "Nice photo!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    # VIP the sender so the one-minute wait does not block the test.
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Friend")
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert fake.sent == [("t1", "Nice photo!")]
    assert seen_media["media_url"] == "https://cdn.example/p.jpg"
    assert seen_media["media_type"] == "photo"


@pytest.mark.asyncio
async def test_tricky_message_creates_draft_not_reply(tmp_vault, tmp_path, monkeypatch):
    """A money message is drafted for Sir, never auto-sent on the platform."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "can you send me money?", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "Let me check with Rayyan.", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    sent_telegram = []
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent_telegram.append(text) or True),
    )
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    result = await responder.poll_once()
    # Nothing sent on Messenger — the draft went to Sir on Telegram.
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    draft = responder.get_pending_draft()
    assert draft is not None
    assert draft["sender_name"] == "Omar"
    assert draft["draft_reply"] == "Let me check with Rayyan."
    assert len(sent_telegram) == 1
    assert "Draft reply" in sent_telegram[0]


@pytest.mark.asyncio
async def test_send_draft_reply(tmp_vault, tmp_path, monkeypatch):
    """Sir's approved draft is sent on the platform and the draft clears."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    responder._pending_drafts["t1"] = {
        "platform": "messenger", "thread_id": "t1", "message_id": "m1",
        "sender_name": "Omar", "text": "can you send me money?",
        "draft_reply": "Let me check with Rayyan.",
    }
    fake = _FakeClient(user_id="111111", messages=[])
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    result = await responder.send_draft_reply("t1", "Let me check with Rayyan.")
    assert result["ok"] is True
    assert fake.sent == [("t1", "Let me check with Rayyan.")]
    assert responder.get_pending_draft() is None


@pytest.mark.asyncio
async def test_send_dm_to_name(tmp_vault, tmp_path, monkeypatch):
    """Jarvis sends a DM to a person by name when Sir asks on Telegram."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar Haddad", "hi", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.notification_engine.notification_engine.send_notification",
        lambda notification: _noop_coro(True),
    )
    result = await responder.send_dm_to_name("Omar", "I will be there at 5.")
    assert result["ok"] is True
    assert result["sender_name"] == "Omar Haddad"
    assert fake.sent == [("t1", "I will be there at 5.")]
    # Unknown name: not found, nothing sent.
    result = await responder.send_dm_to_name("Nobody", "hello")
    assert result["ok"] is False
    assert result["reason"] == "not_found"


@pytest.mark.asyncio
async def test_maybe_nudge_fires_once_after_hours(tmp_path, monkeypatch):
    """A thread waiting past the nudge window gets one Telegram nudge."""
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    responder._first_reply_at = {
        "messenger": {"t1": datetime.now(UTC) - timedelta(hours=5)},
    }
    sent = []
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )

    async def _noop_coro(value):
        return value

    await responder._maybe_nudge("messenger", "t1", "Omar")
    assert len(sent) == 1
    assert "still waiting" in sent[0]
    # Second call: already nudged, no second message.
    await responder._maybe_nudge("messenger", "t1", "Omar")
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_send_daily_digest(tmp_path, monkeypatch):
    """The digest sends a Telegram summary when there is activity."""
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )
    # No activity: nothing sent.
    assert await responder.send_daily_digest() is False
    assert sent == []
    responder._record_activity(
        "instagram", {"sender_name": "Layla", "text": "hello"}, "Hi!", False,
    )
    assert await responder.send_daily_digest() is True
    assert len(sent) == 1
    assert "Layla" in sent[0]


# --- Abilities wave 2: quiet hours, spam filter, away questions ---

@pytest.mark.asyncio
async def test_quiet_hours_sends_morning_reply_once(tmp_vault, tmp_path, monkeypatch):
    """Late at night Jarvis sends one short 'morning' reply, not a full reply."""
    from backend.services.dm_responder import DMResponder, _in_quiet_hours

    monkeypatch.setattr("backend.services.dm_responder.settings.dm_quiet_hours_start", "00:00")
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_quiet_hours_end", "23:59")
    assert _in_quiet_hours() is True
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Friend", "hello", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "FULL REPLY", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    # Only the short morning reply went out, not the full LLM reply.
    assert len(fake.sent) == 1
    assert "morning" in fake.sent[0][1]
    assert "FULL REPLY" not in fake.sent[0][1]
    # A second message in the same thread that night gets nothing.
    incoming2 = [_msg("messenger", "t1", "999", "Friend", "hello again", "m2")]
    fake._messages = incoming2
    result = await responder.poll_once()
    assert len(fake.sent) == 1


@pytest.mark.asyncio
async def test_abusive_message_mutes_thread(tmp_vault, tmp_path, monkeypatch):
    """An abusive message mutes the thread and flags Sir on Telegram."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "you are stupid", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "Hi!", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)
    sent_telegram = []

    async def _noop_coro(value):
        return value

    async def fake_telegram(text, client=None):
        sent_telegram.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    assert len(sent_telegram) == 1
    assert "muted" in sent_telegram[0]
    # Unmute resumes replies.
    assert responder.unmute_thread("Omar") is True
    assert responder.unmute_thread("Omar") is False


@pytest.mark.asyncio
async def test_away_question_asks_sir_first(tmp_vault, tmp_path, monkeypatch):
    """'When will he be back?' is drafted for Sir, never auto-answered."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "when will he be back?", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "He will be back soon.", "model": "groq"}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)
    sent_telegram = []

    async def fake_telegram(text, client=None):
        sent_telegram.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    draft = responder.get_pending_draft()
    assert draft is not None
    assert draft["sender_name"] == "Omar"
    assert len(sent_telegram) == 1
    assert "when" in sent_telegram[0].lower()


@pytest.mark.asyncio
async def test_custom_rule_reply_beats_llm(tmp_vault, tmp_path, monkeypatch):
    """A matching custom rule is sent as-is, no LLM call."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.rules, "_path", tmp_path / "dm_rules.json")
    monkeypatch.setattr(dm_store.rules, "_loaded", False)
    monkeypatch.setattr(dm_store.rules, "_data", {})
    dm_store.rules.set("r1", {
        "person": "Omar", "topic": "club",
        "reply": "Here is the club link.",
    })
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "tell me about the club", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        raise AssertionError("LLM should not be called when a rule matches")

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert fake.sent == [("t1", "Here is the club link.")]


@pytest.mark.asyncio
async def test_meeting_request_asks_sir_for_times(tmp_vault, tmp_path, monkeypatch):
    """A meeting request asks Sir for times instead of offering any."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    monkeypatch.setattr(dm_store.meetings, "_path", tmp_path / "pending_meetings.json")
    monkeypatch.setattr(dm_store.meetings, "_loaded", False)
    monkeypatch.setattr(dm_store.meetings, "_data", {})
    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "can we meet tomorrow?", "m1")]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)
    sent_telegram = []

    async def fake_telegram(text, client=None):
        sent_telegram.append(text)
        return True

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message", fake_telegram
    )
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 0
    assert fake.sent == []
    assert len(sent_telegram) == 1
    assert "wants to meet" in sent_telegram[0]
    assert len(dm_store.meetings.all()) == 1


@pytest.mark.asyncio
async def test_missed_call_sends_intro_instantly(tmp_vault, tmp_path, monkeypatch):
    """A missed call gets the introduction message at once, no wait."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "Missed voice call", "m1",
                     is_missed_call=True)]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "Hi, this is Jarvis. Rayyan is busy right now."}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    result = await responder.poll_once()
    assert result["messenger"]["replied"] == 1
    assert len(fake.sent) == 1
    assert "Jarvis" in fake.sent[0][1]


@pytest.mark.asyncio
async def test_missed_call_not_sent_twice(tmp_vault, tmp_path, monkeypatch):
    """A missed call already handled is not re-introduced on the next poll."""
    from backend.services.dm_responder import DMResponder

    dm_auth.save_connector("messenger", "cookies", {"cookies": FAKE_COOKIES})
    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    incoming = [_msg("messenger", "t1", "999", "Omar", "Missed voice call", "m1",
                     is_missed_call=True)]
    fake = _FakeClient(user_id="111111", messages=incoming)
    monkeypatch.setattr(responder, "_build_client", lambda platform, method, data: fake)

    async def fake_gen(platform, sender_name, text, client=None, first_reply=True, is_group=False, media_url=None, media_type=None, contact_notes=None, tone=None, busy=None):
        return {"ok": True, "reply": "Hi, this is Jarvis."}

    monkeypatch.setattr("backend.services.dm_responder.generate_dm_reply", fake_gen)
    monkeypatch.setattr("backend.services.dm_responder.settings.dm_vip_contacts", "Omar")
    await responder.poll_once()
    assert len(fake.sent) == 1
    await responder.poll_once()
    assert len(fake.sent) == 1  # no second intro for the same call


@pytest.mark.asyncio
async def test_send_morning_briefing(tmp_path, monkeypatch):
    """The morning briefing sends weather, calendar, birthdays and DMs."""
    from datetime import datetime as _dt

    from backend.services import dm_store
    from backend.services.dm_responder import _AMMAN, DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_irbid_weather",
        lambda: _noop_coro({
            "temp": 18.0, "condition": "clear sky", "wind": 10.0,
            "high": 24.0, "low": 12.0, "rain_chance": 0,
        }),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_briefing_news",
        lambda language="en": _noop_coro([]),
    )
    today = _dt.now(_AMMAN).date().isoformat()
    monkeypatch.setattr(dm_store.calendar, "_path", tmp_path / "calendar.json")
    monkeypatch.setattr(dm_store.calendar, "_loaded", False)
    monkeypatch.setattr(dm_store.calendar, "_data", {})
    dm_store.calendar.set(today, {
        "date": today, "status": "busy", "detail": "football practice",
        "from": f"{today}T17:00:00+03:00", "to": f"{today}T20:00:00+03:00",
    })
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    dm_store.contacts.set("Omar", {"birthday": _dt.now(_AMMAN).strftime("%m-%d")})
    responder._record_activity(
        "instagram", {"sender_name": "Layla", "text": "hello"}, "Hi!", False,
    )
    assert await responder.send_morning_briefing() is True
    assert len(sent) == 1
    assert "Irbid" in sent[0] and "18" in sent[0]
    assert "Busy today" in sent[0] and "football" in sent[0]
    assert "Omar" in sent[0] and "birthday" in sent[0].lower()
    assert "Layla" in sent[0]


@pytest.mark.asyncio
async def test_send_morning_briefing_without_weather(tmp_path, monkeypatch):
    """The briefing still goes out when the weather fetch fails."""
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_irbid_weather",
        lambda: _noop_coro(None),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_briefing_news",
        lambda language="en": _noop_coro([]),
    )
    assert await responder.send_morning_briefing() is True
    assert len(sent) == 1
    assert "Irbid" not in sent[0]
    assert "Good morning" in sent[0]


@pytest.mark.asyncio
async def test_briefing_settings_defaults_and_update(tmp_path, monkeypatch):
    """Briefing settings default to 07:00/text/English/all sections on."""
    from backend.services import dm_store
    from backend.services.dm_responder import (
        get_briefing_settings,
        update_briefing_settings,
    )

    monkeypatch.setattr(dm_store.briefing, "_path", tmp_path / "briefing.json")
    monkeypatch.setattr(dm_store.briefing, "_loaded", False)
    monkeypatch.setattr(dm_store.briefing, "_data", {})
    settings = get_briefing_settings()
    assert settings["time"] == "07:00"
    assert settings["voice"] is False
    assert settings["language"] == "en"
    assert all(settings["sections"].values())
    updated = update_briefing_settings({"time": "08:30", "sections": {"news": False}})
    assert updated["time"] == "08:30"
    assert updated["sections"]["news"] is False
    assert updated["sections"]["weather"] is True  # other sections untouched
    assert get_briefing_settings()["time"] == "08:30"


@pytest.mark.asyncio
async def test_fetch_briefing_news(monkeypatch):
    """The news fetch returns up to two headlines per group."""
    from backend.services.dm_responder import _fetch_briefing_news
    from backend.services.web_search_service import WebSearchService

    async def _fake_search(self, query, max_results=5):
        if "world" in query:
            return [
                {"title": "World headline one", "snippet": "Big thing happened.", "url": "https://x.example/1"},
                {"title": "World headline two", "snippet": "Another thing.", "url": "https://x.example/2"},
                {"title": "World headline three", "snippet": "Third.", "url": "https://x.example/3"},
            ]
        return [{"title": f"{query} headline", "snippet": "Snippet.", "url": "https://x.example/9"}]

    monkeypatch.setattr(WebSearchService, "search", _fake_search)
    headlines = await _fetch_briefing_news("en")
    world = [h for h in headlines if h["group"] == "World"]
    assert len(world) == 2  # capped at two per group
    assert world[0]["title"] == "World headline one"
    assert len({h["group"] for h in headlines}) == 4


@pytest.mark.asyncio
async def test_send_morning_briefing_with_news(tmp_path, monkeypatch):
    """The briefing includes a news section from the live web search."""
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_irbid_weather",
        lambda: _noop_coro(None),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_briefing_news",
        lambda language="en": _noop_coro([
            {"group": "World", "title": "World headline one", "snippet": "Big thing happened."},
            {"group": "Jordan", "title": "Jordan headline", "snippet": ""},
        ]),
    )
    assert await responder.send_morning_briefing() is True
    assert len(sent) == 1
    assert "Today's news" in sent[0]
    assert "World headline one" in sent[0]
    assert "Jordan headline" in sent[0]


@pytest.mark.asyncio
async def test_send_morning_briefing_voice(tmp_path, monkeypatch):
    """When voice is on, the briefing goes out as a voice note."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder, update_briefing_settings

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent_text = []
    sent_voice = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(dm_store.briefing, "_path", tmp_path / "briefing.json")
    monkeypatch.setattr(dm_store.briefing, "_loaded", False)
    monkeypatch.setattr(dm_store.briefing, "_data", {})
    update_briefing_settings({"voice": True})
    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent_text.append(text) or True),
    )
    monkeypatch.setattr(
        "backend.services.dm_voice.send_telegram_voice_reply",
        lambda text, client=None: _noop_coro(sent_voice.append(text) or True),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_irbid_weather",
        lambda: _noop_coro(None),
    )
    monkeypatch.setattr(
        "backend.services.dm_responder._fetch_briefing_news",
        lambda language="en": _noop_coro([]),
    )
    assert await responder.send_morning_briefing() is True
    assert len(sent_voice) == 1 and "Good morning" in sent_voice[0]
    assert len(sent_text) == 0


@pytest.mark.asyncio
async def test_save_contact_details_phone(tmp_path, monkeypatch):
    """A phone number shared in a DM is saved to the contact card."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    saved = await responder._save_contact_details(
        "Omar", "hey my number is +962 7 8880 9843, call me"
    )
    assert saved == ["phone +962788809843"]
    assert dm_store.contacts.get("Omar", {}).get("phone") == "+962788809843"
    assert len(sent) == 1 and "Omar" in sent[0]
    # A repeat is silent — no second note.
    saved = await responder._save_contact_details(
        "Omar", "my number is +962 7 8880 9843"
    )
    assert saved == []
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_save_contact_details_instagram_and_ignores_noise(tmp_path, monkeypatch):
    """An @handle is saved; emails and bare numbers are not."""
    from backend.services import dm_store
    from backend.services.dm_responder import DMResponder

    responder = DMResponder(seen_path=str(tmp_path / "dm_seen.json"))
    sent = []

    async def _noop_coro(value):
        return value

    monkeypatch.setattr(
        "backend.services.telegram_notifier.send_telegram_message",
        lambda text, client=None: _noop_coro(sent.append(text) or True),
    )
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    saved = await responder._save_contact_details(
        "Layla", "follow me @layla.jo on instagram"
    )
    assert saved == ["instagram @layla.jo"]
    assert dm_store.contacts.get("Layla", {}).get("instagram") == "layla.jo"
    # An email address is not a handle, and bare numbers are not phones.
    saved = await responder._save_contact_details(
        "Omar", "email me at omar@gmail.com, I have 5 tickets"
    )
    assert saved == []
    assert dm_store.contacts.get("Omar", {}) == {}
