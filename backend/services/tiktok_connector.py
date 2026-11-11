# ====================================================================
# JARVIS OMEGA — TikTok Connector (Business Messaging, OAuth 2.0)
# ====================================================================
"""
TikTok connector: Business Messaging API client (OAuth 2.0).

The app credentials (client key + client secret) and the user tokens
(access + refresh + open_id) live encrypted in the credentials vault.
A token from the ``TIKTOK_ACCESS_TOKEN`` env var is used as a
fallback when the vault is empty. Sir connects with /connect tiktok
on Telegram: he authorizes Jarvis in TikTok, the callback code is
exchanged for tokens server-side, and the tokens are never logged or
echoed back. /disconnect tiktok removes them — the only way the
tokens leave the vault.

What TikTok actually allows — read this before promising anything:
* Business Messaging works ONLY with a TikTok BUSINESS account.
  Personal and Creator accounts are unsupported.
* It needs a developer app on business-api.tiktok.com PLUS a manual
  Business Messaging application and approval (business documents,
  privacy policy, data-handling details).
* Replies are ONLY allowed within a 48-hour window after the
  customer's last message, at most 10 consecutive messages per
  window. Jarvis can NEVER start a DM — it can only reply to
  someone who messaged the business first.
* Business Messaging is NOT available for accounts registered in
  the EEA, Switzerland, or the UK.
* Access tokens are short-lived (about 2 hours), so messaging calls
  refresh the token once and retry when TikTok answers 401.

VERIFICATION STATUS — read before trusting the messaging calls:
* VERIFIED (multiple independent sources, incl. the Appwrite
  implementation and TikTok's own Login Kit guides): the authorize
  URL, the token endpoint, the form-urlencoded code exchange and
  refresh, and user info as GET /v2/user/info/?fields=... — NOT a
  POST, despite the task draft saying POST.
* NOT VERIFIED against TikTok's official docs: the Business
  Messaging host (business-api.tiktok.com) and the conversation /
  send paths. TikTok's official Business API docs render
  client-side and could not be read. The host and paths come from
  the third-party ``bububa/tiktok-business`` Go SDK docs — which
  mirror the official Business API v1.3 docs — corroborated by
  Chatwoot, Supsis and respond.io docs:
    - GET  /business/message/conversation/list/
         (business_id, conversation_type, limit, cursor)
    - POST /business/message/send/
         (business_id, recipient_type=CONVERSATION,
          recipient=<conversation_id>, message_type=TEXT,
          text={body})
  The paths are flagged UNVERIFIED in the constants below. A live
  call against a real approved Business Messaging app is REQUIRED
  before claiming these work.
* OPEN QUESTION: whether a Login Kit token (from
  open.tiktokapis.com/v2/oauth/token/) is accepted on
  business-api.tiktok.com, or whether the Business API's own
  /tt_user/oauth2/token/ endpoint must be used instead. The SDK
  docs reference the latter for the open_id that becomes
  business_id. Live verification must settle this too.

Send operations are exposed as tools at TIER_4_EXTERNAL, so the
approval gateway asks Sir before any of them runs.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("tiktok_connector")

# --- Verified: Login Kit / Display API (open.tiktokapis.com) ---------
_API = "https://open.tiktokapis.com/v2"
_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_PATH = "/oauth/token/"
_USER_INFO_PATH = "/user/info/"

# --- UNVERIFIED: Business Messaging API ------------------------------
# Attested via the bububa/tiktok-business Go SDK docs (which mirror
# TikTok's official Business API v1.3 docs) + Chatwoot / Supsis /
# respond.io docs. TikTok's official Business API docs render
# client-side and could not be read, so these are best-known values,
# NOT confirmed facts. Do not present them as verified.
_BUSINESS_API = "https://business-api.tiktok.com"
_MSG_CONVERSATION_LIST_PATH = "/business/message/conversation/list/"  # UNVERIFIED
_MSG_SEND_PATH = "/business/message/send/"  # UNVERIFIED (attested as a path fragment)

# Scopes the OAuth flow requests. user.info.basic is added by default
# for Login Kit apps; the message.* scopes need Business Messaging
# approval on the app.
DEFAULT_SCOPES = (
    "user.info.basic,message.list.read,message.list.send,message.list.manage"
)

# A text message may be at most 6,000 characters.
_MAX_MESSAGE_CHARS = 6000

VAULT_CLIENT_KEY = "tiktok_client_key"
VAULT_CLIENT_SECRET = "tiktok_client_secret"
VAULT_ACCESS_TOKEN = "tiktok_access_token"
VAULT_REFRESH_TOKEN = "tiktok_refresh_token"
VAULT_OPEN_ID = "tiktok_open_id"


def _vault_get(key: str) -> str | None:
    try:
        return credentials_vault.get(key)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("tiktok_vault_read_failed", key=key, error=str(e))
        return None


def client_key() -> str | None:
    """The TikTok app client key: vault first, env as fallback."""
    saved = _vault_get(VAULT_CLIENT_KEY)
    if saved:
        return saved
    env = (os.environ.get("TIKTOK_CLIENT_KEY") or "").strip()
    return env or None


def client_secret() -> str | None:
    """The TikTok app client secret: vault first, env as fallback."""
    saved = _vault_get(VAULT_CLIENT_SECRET)
    if saved:
        return saved
    env = (os.environ.get("TIKTOK_CLIENT_SECRET") or "").strip()
    return env or None


def save_client_credentials(key: str, secret: str) -> None:
    """Store the app's client key + secret encrypted in the vault."""
    credentials_vault.set(VAULT_CLIENT_KEY, (key or "").strip(), category="connector")
    credentials_vault.set(
        VAULT_CLIENT_SECRET, (secret or "").strip(), category="connector"
    )


def delete_client_credentials() -> bool:
    """Remove the app credentials. True when at least one was stored."""
    return credentials_vault.delete(VAULT_CLIENT_KEY) | credentials_vault.delete(
        VAULT_CLIENT_SECRET
    )


def token() -> str | None:
    """The TikTok access token: vault first, env as fallback."""
    saved = _vault_get(VAULT_ACCESS_TOKEN)
    if saved:
        return saved
    env = (os.environ.get("TIKTOK_ACCESS_TOKEN") or "").strip()
    return env or None


def refresh_token() -> str | None:
    """The stored TikTok refresh token, if any."""
    return _vault_get(VAULT_REFRESH_TOKEN)


def open_id() -> str | None:
    """The connected account's open_id — also the business_id for messaging."""
    return _vault_get(VAULT_OPEN_ID)


def is_connected() -> bool:
    return token() is not None


def _save_tokens(
    access_token: str, refresh: str | None, open_id_value: str | None
) -> None:
    credentials_vault.set(
        VAULT_ACCESS_TOKEN, (access_token or "").strip(), category="connector"
    )
    if refresh:
        credentials_vault.set(
            VAULT_REFRESH_TOKEN, refresh.strip(), category="connector"
        )
    if open_id_value:
        credentials_vault.set(
            VAULT_OPEN_ID, open_id_value.strip(), category="connector"
        )


def delete_tokens() -> bool:
    """Remove the stored tokens + open_id. True when any was stored."""
    removed = False
    for key in (VAULT_ACCESS_TOKEN, VAULT_REFRESH_TOKEN, VAULT_OPEN_ID):
        removed = credentials_vault.delete(key) or removed
    return removed


def get_auth_url(
    redirect_uri: str,
    scopes: list[str] | str | None = None,
    state: str = "",
) -> str:
    """Build the TikTok authorize URL Sir opens to grant access."""
    key = client_key()
    if not key:
        raise ValueError(
            "TikTok client key is not configured — save the app credentials first."
        )
    if scopes is None:
        scope = DEFAULT_SCOPES
    elif isinstance(scopes, list):
        scope = ",".join(scopes)
    else:
        scope = scopes
    params: dict[str, str] = {
        "client_key": key,
        "scope": scope,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    return f"{_AUTH_URL}?{urlencode(params)}"


async def _request(
    method: str,
    url: str,
    tok: str | None = None,
    json_body: dict[str, Any] | None = None,
    form_data: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One TikTok API call. Returns {"ok", "status", "data"/"error"}."""
    headers: dict[str, str] = {"User-Agent": "JARVIS-OMEGA/1.0"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.request(
            method, url, headers=headers,
            json=json_body, data=form_data, params=params,
        )
        if resp.status_code >= 400:
            error = resp.text[:300]
            try:
                body = resp.json()
                if isinstance(body, dict):
                    error = str(
                        body.get("error_description")
                        or body.get("error")
                        or body.get("message")
                        or error
                    )[:300]
            except (ValueError, TypeError):
                pass
            return {"ok": False, "status": resp.status_code, "error": error}
        if resp.status_code == 204:
            return {"ok": True, "status": 204, "data": {}}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "status": 0, "error": str(e)[:300]}
    finally:
        if own_client:
            await client.aclose()


async def _post_token(
    form_data: dict[str, str], client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """POST the OAuth token endpoint (form-urlencoded)."""
    return await _request(
        "POST", f"{_API}{_TOKEN_PATH}", form_data=form_data, client=client
    )


async def exchange_code(
    code: str, redirect_uri: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Exchange an authorize code for tokens; stores them on success.

    Returns {"ok": True, "open_id": ...} or {"ok": False, "error": ...}.
    """
    key = client_key()
    secret = client_secret()
    if not key or not secret:
        return {
            "ok": False,
            "error": "TikTok app credentials are not configured — save the client key and secret first.",
        }
    result = await _post_token(
        {
            "client_key": key,
            "client_secret": secret,
            "code": (code or "").strip(),
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    access = data.get("access_token")
    if not access:
        return {"ok": False, "error": "TikTok did not return an access token."}
    _save_tokens(access, data.get("refresh_token"), data.get("open_id"))
    return {"ok": True, "open_id": data.get("open_id")}


async def refresh_access_token(
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Mint a fresh access token from the stored refresh token.

    TikTok may rotate the refresh token — the newly returned value is
    persisted when it changes. Returns the new access token, or None.
    """
    key = client_key()
    secret = client_secret()
    refresh = refresh_token()
    if not key or not secret or not refresh:
        return None
    result = await _post_token(
        {
            "client_key": key,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
        client=client,
    )
    if not result.get("ok"):
        log.warning(
            "tiktok_refresh_failed",
            error=str(result.get("error", ""))[:200],
        )
        return None
    data = result["data"] or {}
    access = data.get("access_token")
    if not access:
        return None
    _save_tokens(access, data.get("refresh_token"), data.get("open_id"))
    return access


async def verify_token(
    tok: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Check an access token with GET /v2/user/info/.

    Returns {"open_id", "display_name", "avatar_url"}, or None.
    """
    tok = (tok or "").strip()
    if not tok:
        return None
    result = await _request(
        "GET",
        f"{_API}{_USER_INFO_PATH}",
        tok=tok,
        params={"fields": "open_id,display_name,avatar_url"},
        client=client,
    )
    if not result.get("ok"):
        return None
    user = ((result["data"] or {}).get("data") or {}).get("user") or {}
    if not user.get("open_id"):
        return None
    return {
        "open_id": user.get("open_id"),
        "display_name": user.get("display_name"),
        "avatar_url": user.get("avatar_url"),
    }


async def status(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Connection state: connected, display name."""
    tok = token()
    if not tok:
        return {"connected": False, "display_name": None}
    info = await verify_token(tok, client=client)
    if info is None:
        return {"connected": False, "display_name": None}
    return {"connected": True, "display_name": info.get("display_name")}


async def _business_request(
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
    _retried: bool = False,
) -> dict[str, Any]:
    """One Business Messaging API call.

    The Business API wraps payloads in a {"code", "message", "data"}
    envelope (code 0 = success). Access tokens are short-lived, so a
    401 refreshes the token once and retries.
    """
    tok = token()
    if not tok:
        return {"ok": False, "status": 0, "error": "TikTok is not connected."}
    result = await _request(
        method, f"{_BUSINESS_API}{path}", tok=tok,
        json_body=json_body, params=params, client=client,
    )
    if result.get("status") == 401 and not _retried:
        new_tok = await refresh_access_token(client=client)
        if new_tok:
            return await _business_request(
                method, path, json_body, params, client, _retried=True
            )
    if not result.get("ok"):
        return result
    body = result["data"] or {}
    code = body.get("code")
    if code is not None and code != 0:
        return {
            "ok": False,
            "status": result["status"],
            "error": str(body.get("message", "TikTok error"))[:300],
        }
    return {"ok": True, "status": result["status"], "data": body.get("data", body)}


# --------------------------------------------------------------------
# Read
# --------------------------------------------------------------------

async def list_conversations(
    limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """List the Business Account's DM conversations.

    UNVERIFIED endpoint (see module docstring): GET
    /business/message/conversation/list/ on business-api.tiktok.com.
    """
    tok = token()
    if not tok:
        return {"ok": False, "error": "TikTok is not connected."}
    business_id = open_id()
    if not business_id:
        return {
            "ok": False,
            "error": "TikTok open_id is not stored — reconnect TikTok first.",
        }
    result = await _business_request(
        "GET",
        _MSG_CONVERSATION_LIST_PATH,
        params={
            "business_id": business_id,
            "limit": min(max(limit, 1), 100),
            "cursor": 0,
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    conversations = data.get("conversations") or []
    return {
        "ok": True,
        "count": len(conversations),
        "has_more": data.get("has_more", False),
        "cursor": data.get("cursor", 0),
        "conversations": [
            {
                "conversation_id": c.get("conversation_id"),
                "up_time": c.get("up_time"),
                "referral": c.get("referral"),
            }
            for c in conversations
        ],
    }


# --------------------------------------------------------------------
# Write — needs the tokens; the tool gates it at TIER_4_EXTERNAL so
# Sir approves before it runs. Replies only: TikTok never lets a
# business start a conversation, and only inside the 48-hour window.
# --------------------------------------------------------------------

async def send_message(
    conversation_id: str,
    text: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Reply to a TikTok DM conversation (text only).

    UNVERIFIED endpoint (see module docstring): POST
    /business/message/send/ on business-api.tiktok.com.
    Returns {"ok", "message_id"}.
    """
    tok = token()
    if not tok:
        return {"ok": False, "error": "TikTok is not connected."}
    business_id = open_id()
    if not business_id:
        return {
            "ok": False,
            "error": "TikTok open_id is not stored — reconnect TikTok first.",
        }
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Message text is empty."}
    if len(text) > _MAX_MESSAGE_CHARS:
        return {
            "ok": False,
            "error": "Message is too long — TikTok allows 6,000 characters.",
        }
    result = await _business_request(
        "POST",
        _MSG_SEND_PATH,
        json_body={
            "business_id": business_id,
            "recipient_type": "CONVERSATION",
            "recipient": (conversation_id or "").strip(),
            "message_type": "TEXT",
            "text": {"body": text},
        },
        client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    message = data.get("message") or {}
    return {"ok": True, "message_id": message.get("message_id")}
