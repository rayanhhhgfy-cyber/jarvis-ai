# ====================================================================
# JARVIS OMEGA — Google Connector (OAuth + Gmail + Calendar + Drive)
# ====================================================================
"""
Google connector: Gmail, Calendar and Drive behind ONE OAuth login.

Unlike GitHub/Vercel (a pasted API token), Google does not accept a
pasted password — 2FA blocks it. Jarvis needs an OAuth client
(client_id + client_secret, created once in Google Cloud Console) and
a refresh token, obtained when Sir signs in with Google and grants
the scopes below. The refresh token lives encrypted in the vault and
is used to mint short-lived access tokens on demand.

Scopes:
  * https://www.googleapis.com/auth/gmail.readonly — read mail
  * https://www.googleapis.com/auth/gmail.send — send mail
  * https://www.googleapis.com/auth/calendar — read + write events
  * https://www.googleapis.com/auth/drive.readonly — read Drive files

Flow:
  1. Sir creates an OAuth client (Desktop app type) in Google Cloud
     Console and pastes the client_id + client_secret with
     /connect google (they are stored encrypted, never echoed).
  2. /connect google gives him a sign-in link; he signs in with his
     Google account and grants the scopes.
  3. Google redirects to the backend callback, which exchanges the
     code for a refresh token and stores it. Done — Jarvis can now
     read his REAL Gmail, Calendar and Drive. (Until now Jarvis only
     had its own separate calendar; his real calendar was invisible.)

Drive is read-only here on purpose: listing, searching and reading
files. Uploading to Drive is a write that can be added later.
"""

from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.services.credentials_vault import credentials_vault
from shared.logger import get_logger

log = get_logger("google_connector")

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL = "https://gmail.googleapis.com/gmail/v1"
_CALENDAR = "https://www.googleapis.com/calendar/v3"
_DRIVE = "https://www.googleapis.com/drive/v3"

CLIENT_ID_KEY = "google_client_id"
CLIENT_SECRET_KEY = "google_client_secret"
REFRESH_TOKEN_KEY = "google_refresh_token"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]

DEFAULT_REDIRECT_URI = "https://jarvis-ai-6c11.onrender.com/api/oauth/google/callback"


def redirect_uri() -> str:
    return (os.environ.get("GOOGLE_REDIRECT_URI") or DEFAULT_REDIRECT_URI).strip()


def _vault_get(key: str) -> str | None:
    try:
        return credentials_vault.get(key)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("google_vault_read_failed", key=key, error=str(e))
        return None


def client_id() -> str | None:
    return _vault_get(CLIENT_ID_KEY) or (os.environ.get("GOOGLE_CLIENT_ID") or "").strip() or None


def client_secret() -> str | None:
    return _vault_get(CLIENT_SECRET_KEY) or (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip() or None


def refresh_token() -> str | None:
    return _vault_get(REFRESH_TOKEN_KEY) or (os.environ.get("GOOGLE_REFRESH_TOKEN") or "").strip() or None


def is_connected() -> bool:
    return refresh_token() is not None


def has_client() -> bool:
    return client_id() is not None and client_secret() is not None


def save_client(client_id_value: str, client_secret_value: str) -> None:
    """Store the OAuth client credentials encrypted in the vault."""
    credentials_vault.set(CLIENT_ID_KEY, client_id_value.strip(), category="connector")
    credentials_vault.set(CLIENT_SECRET_KEY, client_secret_value.strip(), category="connector")


def save_refresh_token(token: str) -> None:
    credentials_vault.set(REFRESH_TOKEN_KEY, token.strip(), category="connector")


def delete_all() -> bool:
    """Remove every Google credential. Returns True if any was stored."""
    removed = False
    for key in (CLIENT_ID_KEY, CLIENT_SECRET_KEY, REFRESH_TOKEN_KEY):
        removed = credentials_vault.delete(key) or removed
    return removed


def get_auth_url(state: str = "telegram") -> str | None:
    """The Google sign-in link Sir opens to grant the scopes."""
    cid = client_id()
    if not cid:
        return None
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    code: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Swap an auth code for tokens; store the refresh token."""
    cid, secret = client_id(), client_secret()
    if not cid or not secret:
        return {"ok": False, "error": "Google OAuth client is not set up — /connect google first."}
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.post(_TOKEN_URL, data={
            "code": code,
            "client_id": cid,
            "client_secret": secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
        if resp.status_code != 200:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        refresh = data.get("refresh_token")
        if not refresh:
            return {"ok": False, "error": "Google did not return a refresh token. Try again."}
        save_refresh_token(refresh)
        return {"ok": True, "email": await _profile_email(data.get("access_token"), client=client)}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "error": str(e)[:300]}
    finally:
        if own_client:
            await client.aclose()


async def get_access_token(client: httpx.AsyncClient | None = None) -> str | None:
    """Mint a short-lived access token from the stored refresh token."""
    refresh, cid, secret = refresh_token(), client_id(), client_secret()
    if not refresh or not cid or not secret:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.post(_TOKEN_URL, data={
            "refresh_token": refresh,
            "client_id": cid,
            "client_secret": secret,
            "grant_type": "refresh_token",
        })
        if resp.status_code != 200:
            log.warning("google_token_refresh_failed", status=resp.status_code)
            return None
        return resp.json().get("access_token")
    except (httpx.HTTPError, ValueError) as e:
        log.warning("google_token_refresh_failed", error=str(e))
        return None
    finally:
        if own_client:
            await client.aclose()


async def _profile_email(
    access_token: str | None, client: httpx.AsyncClient | None = None
) -> str | None:
    """The Gmail address of the connected account."""
    if not access_token:
        return None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            f"{_GMAIL}/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("emailAddress")
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own_client:
            await client.aclose()


async def status(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Connection state: connected, and the Gmail address when known."""
    if not is_connected():
        return {"connected": False, "email": None}
    access = await get_access_token(client=client)
    email = await _profile_email(access, client=client) if access else None
    return {"connected": access is not None, "email": email}


async def _api(
    method: str,
    url: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One Google API call with a fresh access token."""
    access = await get_access_token(client=client)
    if not access:
        return {"ok": False, "error": "Google is not connected — /connect google first."}
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20)
    try:
        resp = await client.request(
            method, url,
            headers={"Authorization": f"Bearer {access}"},
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


# --------------------------------------------------------------------
# Gmail
# --------------------------------------------------------------------

async def list_messages(
    query: str = "", limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {"maxResults": min(limit, 100)}
    if query:
        params["q"] = query
    result = await _api("GET", f"{_GMAIL}/users/me/messages", params=params, client=client)
    if not result.get("ok"):
        return result
    messages = (result["data"] or {}).get("messages") or []
    return {"ok": True, "count": len(messages), "messages": messages}


def _header(headers: list[dict[str, Any]], name: str) -> str:
    for h in headers or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""


async def get_message(
    message_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    result = await _api(
        "GET", f"{_GMAIL}/users/me/messages/{message_id}",
        params={"format": "full"}, client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    headers = (data.get("payload") or {}).get("headers") or []
    snippet = data.get("snippet") or ""
    return {
        "ok": True,
        "id": data.get("id"),
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "subject": _header(headers, "Subject"),
        "date": _header(headers, "Date"),
        "snippet": snippet,
    }


async def send_message(
    to: str, subject: str, body: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    raw = (
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}"
    )
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    result = await _api(
        "POST", f"{_GMAIL}/users/me/messages/send",
        json_body={"raw": encoded}, client=client,
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "id": (result["data"] or {}).get("id")}


# --------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------

async def list_events(
    time_min: str = "",
    time_max: str = "",
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "maxResults": min(limit, 100),
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    result = await _api(
        "GET", f"{_CALENDAR}/calendars/primary/events", params=params, client=client
    )
    if not result.get("ok"):
        return result
    events = (result["data"] or {}).get("items") or []
    return {
        "ok": True,
        "count": len(events),
        "events": [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
                "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
                "location": e.get("location"),
            }
            for e in events
        ],
    }


async def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": "Asia/Amman"},
        "end": {"dateTime": end, "timeZone": "Asia/Amman"},
    }
    if description:
        body["description"] = description
    result = await _api(
        "POST", f"{_CALENDAR}/calendars/primary/events",
        json_body=body, client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    return {"ok": True, "id": data.get("id"), "link": data.get("htmlLink")}


# --------------------------------------------------------------------
# Drive (read-only)
# --------------------------------------------------------------------

async def list_files(
    query: str = "", limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "pageSize": min(limit, 100),
        "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        "orderBy": "modifiedTime desc",
    }
    if query:
        params["q"] = query
    result = await _api("GET", f"{_DRIVE}/files", params=params, client=client)
    if not result.get("ok"):
        return result
    files = (result["data"] or {}).get("files") or []
    return {
        "ok": True,
        "count": len(files),
        "files": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "mimeType": f.get("mimeType"),
                "modifiedTime": f.get("modifiedTime"),
                "link": f.get("webViewLink"),
            }
            for f in files
        ],
    }


async def search_files(
    query: str, limit: int = 10, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    return await list_files(f"name contains '{query}'", limit=limit, client=client)


async def get_file(
    file_id: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    result = await _api(
        "GET", f"{_DRIVE}/files/{file_id}",
        params={"fields": "id,name,mimeType,modifiedTime,webViewLink,size"},
        client=client,
    )
    if not result.get("ok"):
        return result
    data = result["data"] or {}
    return {
        "ok": True,
        "id": data.get("id"),
        "name": data.get("name"),
        "mimeType": data.get("mimeType"),
        "modifiedTime": data.get("modifiedTime"),
        "size": data.get("size"),
        "link": data.get("webViewLink"),
    }
