# ====================================================================
# JARVIS OMEGA — X (Twitter) Connector (OAuth 2.0, user context)
# ====================================================================
"""
X connector: read AND write DMs via the X API v2, OAuth 2.0 user
context.

PAY-PER-USE — READ THIS FIRST: since February 2026 new X developers
default to pay-per-use with NO free tier. DM reads and sends are
billed per request (roughly $0.010 per DM read, $0.015 per DM sent).
Rayyan must approve the spend and add prepaid credits to the X
developer account BEFORE this is used live, or every call will fail
on billing. (VENTURE-100 rule: $0 spend without his written OK.)

Auth: OAuth 2.0 Authorization Code with PKCE (S256). The app
credentials (client id + secret) live encrypted in the vault under
``x_client_id`` / ``x_client_secret``; the user tokens under
``x_access_token`` / ``x_refresh_token``. User access tokens expire
after 2 hours — ``refresh_access_token`` trades the stored refresh
token for a new pair (the ``offline.access`` scope is what makes a
refresh token exist at all). Tokens are verified with GET /2/users/me
BEFORE anything is stored, and are never logged or echoed back.
/disconnect x removes all four — the only way they leave the vault.

Endpoints (X API v2, user context; scopes dm.read, dm.write,
users.read, tweet.read, offline.access):
* GET  /2/users/me — who the token belongs to.
* GET  /2/dm_events — recent DM events. ``list_dm_conversations``
  groups these by dm_conversation_id, because X has NO
  conversation-list endpoint — GET /2/dm_conversations does not
  exist as a list call (POST /2/dm_conversations only creates GROUP
  conversations).
* GET  /2/dm_conversations/:id/dm_events — events in one conversation.
* POST /2/dm_conversations/:id/messages — send into a conversation.
* POST /2/dm_conversations/with/:participant_id/messages — send to a
  user, creating the conversation if needed; this is what
  ``create_dm_conversation`` uses.

Caveat: encrypted (XChat) DMs are invisible to these v2 endpoints —
they return empty for encrypted threads rather than erroring, and
only plaintext DM events from the last 30 days are served.

Write operations are exposed as tools at TIER_4_EXTERNAL, so the
approval gateway asks Sir before any of them runs.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import urllib.parse
from typing import Any

import httpx

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("x_connector")

_X = "https://api.twitter.com/2"
_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
_TOKEN_URL = f"{_X}/oauth2/token"

VAULT_CLIENT_ID = "x_client_id"
VAULT_CLIENT_SECRET = "x_client_secret"
VAULT_ACCESS_TOKEN = "x_access_token"
VAULT_REFRESH_TOKEN = "x_refresh_token"

DEFAULT_SCOPES = ["tweet.read", "users.read", "dm.read", "dm.write", "offline.access"]

_DM_EVENT_FIELDS = (
    "id,event_type,text,created_at,dm_conversation_id,sender_id,participant_ids"
)


def _vault_or_env(vault_key: str, env_name: str) -> str | None:
    try:
        saved = credentials_vault.get(vault_key)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("x_vault_read_failed", key=vault_key, error=str(e))
        saved = None
    if saved:
        return saved
    env = (os.environ.get(env_name) or "").strip()
    return env or None


def client_id() -> str | None:
    """The X OAuth app client id: vault first, X_CLIENT_ID env fallback."""
    return _vault_or_env(VAULT_CLIENT_ID, "X_CLIENT_ID")


def client_secret() -> str | None:
    """The X OAuth app client secret: vault first, X_CLIENT_SECRET env fallback."""
    return _vault_or_env(VAULT_CLIENT_SECRET, "X_CLIENT_SECRET")


def token() -> str | None:
    """The stored user access token: vault first, X_ACCESS_TOKEN env fallback."""
    return _vault_or_env(VAULT_ACCESS_TOKEN, "X_ACCESS_TOKEN")


def refresh_token_value() -> str | None:
    """The stored user refresh token: vault first, X_REFRESH_TOKEN env fallback."""
    return _vault_or_env(VAULT_REFRESH_TOKEN, "X_REFRESH_TOKEN")


def is_connected() -> bool:
    return token() is not None


def _headers(tok: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }


def save_client_credentials(client_id_value: str, client_secret_value: str) -> None:
    """Store the OAuth app credentials encrypted in the vault."""
    credentials_vault.set(VAULT_CLIENT_ID, (client_id_value or "").strip(), category="connector")
    credentials_vault.set(
        VAULT_CLIENT_SECRET, (client_secret_value or "").strip(), category="connector"
    )


def save_tokens(access_token: str, refresh_token: str | None = None) -> None:
    """Store a user token pair encrypted in the vault.

    A refresh token is only overwritten when a new one is given —
    X rotates it on refresh, and a grant without the offline.access
    scope returns none at all.
    """
    credentials_vault.set(VAULT_ACCESS_TOKEN, (access_token or "").strip(), category="connector")
    if refresh_token:
        credentials_vault.set(
            VAULT_REFRESH_TOKEN, refresh_token.strip(), category="connector"
        )


def delete_tokens() -> bool:
    """Remove the user tokens from the vault. True when one was stored."""
    removed = credentials_vault.delete(VAULT_ACCESS_TOKEN)
    removed = credentials_vault.delete(VAULT_REFRESH_TOKEN) or removed
    return removed


def delete_all() -> bool:
    """Remove the app credentials AND the user tokens. True if any existed."""
    removed = delete_tokens()
    removed = credentials_vault.delete(VAULT_CLIENT_ID) or removed
    removed = credentials_vault.delete(VAULT_CLIENT_SECRET) or removed
    return removed


# --------------------------------------------------------------------
# OAuth 2.0 with PKCE
# --------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    """A PKCE verifier + S256 challenge pair (hashlib + base64 only)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def get_auth_url(
    redirect_uri: str,
    scopes: list[str] | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth 2.0 authorize URL + a PKCE pair.

    Returns {"url", "code_verifier", "code_challenge", "state"} — the
    caller must keep the verifier (and state) until the callback, then
    hand the verifier to ``exchange_code``.
    """
    verifier, challenge = _pkce_pair()
    state = state or secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id() or "",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes or DEFAULT_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {
        "url": url,
        "code_verifier": verifier,
        "code_challenge": challenge,
        "state": state,
    }


def _token_auth_headers() -> dict[str, str]:
    """Auth for the token endpoint: Basic (id:secret) when the app is
    confidential, otherwise the client id rides in the form body."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    cid = client_id()
    secret = client_secret()
    if cid and secret:
        raw = f"{cid}:{secret}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    return headers


async def _token_request(
    form: dict[str, str], client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """One POST to the OAuth token endpoint. Parsed JSON, or None."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.post(
            _TOKEN_URL, data=form, headers=_token_auth_headers()
        )
        if resp.status_code != 200:
            log.warning("x_token_request_failed", status=resp.status_code)
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("x_token_request_error", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


async def exchange_code(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Trade an authorization code for tokens; store them, verify the
    user. Returns {"ok": True, "username": ...} or {"ok": False, "error": ...}."""
    cid = client_id()
    if not cid:
        return {
            "ok": False,
            "error": "X app credentials are not set — save the client id and secret first.",
        }
    form = {
        "code": (code or "").strip(),
        "grant_type": "authorization_code",
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    data = await _token_request(form, client=client)
    if data is None or not data.get("access_token"):
        return {
            "ok": False,
            "error": "X rejected the authorization code — it may be expired or already used.",
        }
    save_tokens(data["access_token"], data.get("refresh_token"))
    info = await verify_token(data["access_token"], client=client)
    return {"ok": True, "username": (info or {}).get("username")}


async def refresh_access_token(client: httpx.AsyncClient | None = None) -> str | None:
    """Trade the stored refresh token for a new pair; stores the new
    tokens. Returns the new access token, or None when it fails."""
    refresh = refresh_token_value()
    cid = client_id()
    if not refresh or not cid:
        return None
    form = {
        "refresh_token": refresh,
        "grant_type": "refresh_token",
        "client_id": cid,
    }
    data = await _token_request(form, client=client)
    if data is None or not data.get("access_token"):
        log.warning("x_refresh_failed")
        return None
    save_tokens(data["access_token"], data.get("refresh_token"))
    return data["access_token"]


# --------------------------------------------------------------------
# Token check + status
# --------------------------------------------------------------------

async def verify_token(
    tok: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Check a user token with GET /2/users/me. Returns id + username + name, or None."""
    tok = (tok or "").strip()
    if not tok:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(f"{_X}/users/me", headers=_headers(tok))
        if resp.status_code != 200:
            return None
        data = (resp.json() or {}).get("data") or {}
        return {
            "id": data.get("id"),
            "username": data.get("username"),
            "name": data.get("name"),
        }
    except (httpx.HTTPError, ValueError) as e:
        log.warning("x_verify_failed", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


async def status(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Connection state: connected, username."""
    tok = token()
    if not tok:
        return {"connected": False, "username": None}
    info = await verify_token(tok, client=client)
    if info is None:
        return {"connected": False, "username": None}
    return {"connected": True, "username": info.get("username")}


async def _request(
    method: str,
    path: str,
    tok: str | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One X API call. Returns {"ok", "status", "data"/"error"}.

    Every DM endpoint needs user context — there are no public reads,
    so a missing token is an error, not an anonymous call.
    """
    tok = tok or token()
    if not tok:
        return {"ok": False, "status": 0, "error": "X is not connected."}
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.request(
            method, f"{_X}{path}", headers=_headers(tok),
            json=json_body, params=params,
        )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        if resp.status_code == 204:
            return {"ok": True, "status": 204, "data": {}}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "status": 0, "error": str(e)[:300]}
    finally:
        if own_client:
            await client.aclose()


def _require_token() -> str | None:
    return token()


# --------------------------------------------------------------------
# Read
# --------------------------------------------------------------------

async def list_dm_conversations(
    limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """DM conversations, newest first — one entry per conversation.

    X has no conversation-list endpoint, so this reads recent DM
    events (GET /2/dm_events, last 30 days only) and keeps the latest
    event of each distinct dm_conversation_id.
    """
    result = await _request(
        "GET", "/dm_events",
        params={
            "max_results": 100,
            "dm_event.fields": _DM_EVENT_FIELDS,
            "event_types": "MessageCreate",
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    events = (result["data"] or {}).get("data") or []
    seen: dict[str, dict[str, Any]] = {}
    for ev in events:
        conv_id = ev.get("dm_conversation_id")
        if not conv_id or conv_id in seen:
            continue
        seen[conv_id] = {
            "dm_conversation_id": conv_id,
            "last_event_id": ev.get("id"),
            "last_text": ev.get("text"),
            "last_sender_id": ev.get("sender_id"),
            "last_created_at": ev.get("created_at"),
        }
        if len(seen) >= limit:
            break
    conversations = list(seen.values())[:limit]
    return {"ok": True, "count": len(conversations), "conversations": conversations}


async def list_dm_events(
    conversation_id: str,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """DM events in one conversation, newest first."""
    result = await _request(
        "GET", f"/dm_conversations/{conversation_id}/dm_events",
        params={
            "max_results": min(limit, 100),
            "dm_event.fields": _DM_EVENT_FIELDS,
            "event_types": "MessageCreate",
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    events = (result["data"] or {}).get("data") or []
    return {
        "ok": True,
        "count": len(events[:limit]),
        "events": [
            {
                "id": e.get("id"),
                "event_type": e.get("event_type"),
                "text": e.get("text"),
                "sender_id": e.get("sender_id"),
                "created_at": e.get("created_at"),
                "dm_conversation_id": e.get("dm_conversation_id"),
            }
            for e in events[:limit]
        ],
    }


# --------------------------------------------------------------------
# Write — every one of these needs the user token; the tools gate them
# at TIER_4_EXTERNAL so Sir approves before any of them runs. Each
# call is also billed by X (pay-per-use), so they never run silently.
# --------------------------------------------------------------------

async def send_dm(
    conversation_id: str,
    text: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send a DM into an existing conversation."""
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "X is not connected — /connect x first."}
    result = await _request(
        "POST", f"/dm_conversations/{conversation_id}/messages",
        tok=tok, json_body={"text": text}, client=client,
    )
    if not result.get("ok"):
        return result
    data = (result["data"] or {}).get("data") or {}
    return {
        "ok": True,
        "conversation_id": data.get("dm_conversation_id"),
        "message_id": data.get("dm_event_id"),
    }


async def create_dm_conversation(
    user_id: str,
    text: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send a DM to a user, creating the conversation if needed."""
    tok = _require_token()
    if not tok:
        return {"ok": False, "error": "X is not connected — /connect x first."}
    result = await _request(
        "POST", f"/dm_conversations/with/{user_id}/messages",
        tok=tok, json_body={"text": text}, client=client,
    )
    if not result.get("ok"):
        return result
    data = (result["data"] or {}).get("data") or {}
    return {
        "ok": True,
        "conversation_id": data.get("dm_conversation_id"),
        "message_id": data.get("dm_event_id"),
    }
