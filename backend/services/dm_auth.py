# ====================================================================
# JARVIS OMEGA — DM Connectors Auth
# ====================================================================
"""
Credential handling for the DM Connectors feature (Messenger + Instagram).

Sir pastes EITHER an email+password pair OR a cookies export in the
dashboard Connectors tab. This module:

* parses pasted cookies (``k=v; ...`` header form, Netscape cookies.txt,
  or a JSON object / JSON list of ``{"name", "value"}`` pairs),
* verifies the login before anything is stored (a lightweight session
  probe for cookies; a real login attempt for email+password),
* stores the verified credentials ENCRYPTED in a dedicated vault file
  (``storage/connectors.json``) via the same Fernet machinery as the
  main credentials vault — never in plaintext, never logged, and never
  returned by any API (only connected/disconnected status is exposed).

Messenger + Instagram personal accounts have no official API for DMs.
The clients here drive the same web/app endpoints the official clients
use (see ``dm_clients.py``). That is against the platforms' rules:
accounts can be locked or banned, and Instagram in particular can
interrupt a login with a verification-code challenge. Login outcomes
are always reported honestly — ``connected`` is only ever set after a
real verification succeeds.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from backend.services.credentials_vault import CredentialsVault
from shared.logger import get_logger

log = get_logger("dm_auth")

PLATFORMS: dict[str, dict[str, str]] = {
    "messenger": {
        "name": "Messenger",
        "vault_key": "connector:messenger",
    },
    "instagram": {
        "name": "Instagram",
        "vault_key": "connector:instagram",
    },
}

# A second vault instance (same Fernet key, separate file) so connector
# secrets never appear in the Settings router's credential listings.
connector_vault = CredentialsVault(storage_path="./storage/connectors.json")


def init_connector_vault(storage_path: str | None = None) -> None:
    """Initialize the connector vault (called from the app lifespan)."""
    if storage_path:
        connector_vault._path = Path(storage_path)
    connector_vault.initialize()


class LoginFailed(Exception):
    """The credentials were rejected by the platform."""


class LoginChallenge(Exception):
    """The platform wants a verification code / checkpoint (2FA, suspicious login)."""


class LoginUnavailable(Exception):
    """Login cannot be attempted (missing library / transport)."""


# --------------------------------------------------------------------
# Cookie parsing
# --------------------------------------------------------------------

def parse_cookies(raw: str) -> dict[str, str]:
    """
    Parse pasted cookies into a ``{name: value}`` dict.

    Accepted forms:
    * ``name=value; name2=value2`` (browser "Copy as cURL" / document.cookie)
    * Netscape cookies.txt (tab-separated, ``#`` comments ignored)
    * JSON object ``{"name": "value"}``
    * JSON list ``[{"name": "...", "value": "..."}]`` (browser export)

    Raises ValueError when nothing usable is found. Cookie *values* are
    never logged by this module.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("No cookies pasted.")

    # JSON forms first.
    if raw.startswith(("{", "[")):
        try:
            data = json.loads(raw)
        except Exception as e:
            raise ValueError(f"Cookies are not valid JSON: {e}")
        if isinstance(data, dict):
            out = {str(k): str(v) for k, v in data.items() if v != ""}
            if not out:
                raise ValueError("JSON cookies object is empty.")
            return out
        if isinstance(data, list):
            out = {}
            for item in data:
                if isinstance(item, dict) and item.get("name") and item.get("value") != "":
                    out[str(item["name"])] = str(item["value"])
            if not out:
                raise ValueError("JSON cookies list has no name/value pairs.")
            return out
        raise ValueError("JSON cookies must be an object or a list of name/value pairs.")

    # Netscape cookies.txt: 7 tab-separated fields, last two are name/value.
    cookies: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] and parts[6]:
                cookies[parts[5].strip()] = parts[6].strip()
            continue
        # Header form: name=value; name2=value2
        for pair in line.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            name, value = name.strip(), value.strip()
            if name and value:
                cookies[name] = value
    if not cookies:
        raise ValueError("Could not parse any cookies from the pasted text.")
    return cookies


# --------------------------------------------------------------------
# Session probing (cookies form)
# --------------------------------------------------------------------

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

_PROBE_URLS = {
    "messenger": "https://www.messenger.com/",
    "instagram": "https://www.instagram.com/",
}


def _looks_logged_in(platform: str, response: httpx.Response) -> bool:
    """True when the probe response shows a logged-in session."""
    url = str(response.url)
    # Both platforms redirect anonymous visitors to a login page.
    if "login" in url or "checkpoint" in url:
        return False
    if response.status_code != 200:
        return False
    if platform == "instagram":
        # The logged-in home page embeds the viewer id; the login page does not.
        return "ds_user_id" in response.text or '"is_logged_in":true' in response.text
    # Messenger: the logged-in page serves the app shell, not the login form.
    return "messenger" in response.text.lower()


async def verify_cookies(
    platform: str,
    cookies: dict[str, str],
    transport: httpx.AsyncHTTPTransport | None = None,
) -> bool:
    """Probe the platform with the given cookies. True = session is live."""
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")
    try:
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            cookies=cookies,
            transport=transport,
            follow_redirects=True,
            timeout=20.0,
        ) as client:
            response = await client.get(_PROBE_URLS[platform])
        ok = _looks_logged_in(platform, response)
        log.info("connector_probe", platform=platform, logged_in=ok)
        return ok
    except Exception as e:
        log.warning("connector_probe_failed", platform=platform, error=str(e))
        return False


# --------------------------------------------------------------------
# Password login
# --------------------------------------------------------------------

async def _messenger_password_login(
    email: str,
    password: str,
    transport: httpx.AsyncHTTPTransport | None = None,
) -> dict[str, str]:
    """
    Log in to Facebook/Messenger with email+password via the web login flow.

    Scrapes the login page for its anti-CSRF tokens, posts to the form's
    own action URL (read from the page, never hardcoded), and returns the
    session cookies on success. Raises LoginChallenge on a checkpoint/2FA
    redirect and LoginFailed on a rejected password.
    """
    async with httpx.AsyncClient(
        headers=_BROWSER_HEADERS,
        transport=transport,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        page = await client.get("https://www.facebook.com/login/")
        if page.status_code != 200:
            raise LoginFailed(f"Login page returned HTTP {page.status_code}")
        html = page.text
        tokens: dict[str, str] = {}
        for name in ("lsd", "jazoest", "m_ts", "li"):
            m = re.search(
                rf'name="{name}" value="([^"]+)"', html
            ) or re.search(rf'name="{name}" value=\'([^\']+)\'', html)
            if m:
                tokens[name] = m.group(1)
        action_m = re.search(r'<form[^>]+action="([^"]+)"', html)
        action = action_m.group(1) if action_m else "/login/device-based/regular/login/"
        if action.startswith("/"):
            action = "https://www.facebook.com" + action
        elif action.startswith("http") is False:
            action = "https://www.facebook.com/" + action.lstrip("/")
        form = {
            "email": email,
            "pass": password,
            "login": "Log In",
            **tokens,
        }
        resp = await client.post(action, data=form)
        url = str(resp.url)
        if "checkpoint" in url or "two_step" in url or "two-factor" in url:
            raise LoginChallenge(
                "Facebook asked for a verification code (checkpoint / 2FA). "
                "Approve the login in the Facebook app, then connect with cookies."
            )
        jar = {c.name: c.value for c in client.cookies.jar}
        if "c_user" in jar:
            return jar
        if "login" in url:
            raise LoginFailed("Facebook rejected the email/password.")
        raise LoginFailed("Login did not produce a session (no c_user cookie).")


def _instagram_password_login(username: str, password: str) -> dict[str, str]:
    """Log in to Instagram with username+password via instagrapi (sync)."""
    try:
        from instagrapi import Client
        from instagrapi.exceptions import (
            BadPassword,
            ChallengeRequired,
            TwoFactorRequired,
        )
    except ImportError as e:
        raise LoginUnavailable(
            "instagrapi is not installed, so password login for Instagram "
            "is unavailable. Connect with cookies instead."
        ) from e
    cl = Client()
    try:
        cl.login(username, password)
    except (ChallengeRequired, TwoFactorRequired) as e:
        raise LoginChallenge(
            "Instagram asked for a verification code. Approve the login in "
            "the Instagram app, then connect with cookies."
        ) from e
    except BadPassword as e:
        raise LoginFailed("Instagram rejected the username/password.") from e
    except Exception as e:
        raise LoginFailed(f"Instagram login failed: {e}") from e
    session: dict[str, str] = {}
    try:
        session = {k: v for k, v in cl.private.cookies.items() if k in ("sessionid", "ds_user_id", "csrftoken", "mid", "ig_did")}
    except Exception:
        session = {}
    if "sessionid" not in session:
        raise LoginFailed("Instagram login did not produce a session.")
    return session


async def login_with_password(
    platform: str,
    email: str,
    password: str,
    transport: httpx.AsyncHTTPTransport | None = None,
) -> dict[str, str]:
    """Log in with email+password; returns the session cookies dict."""
    if platform == "messenger":
        return await _messenger_password_login(email, password, transport=transport)
    if platform == "instagram":
        import asyncio

        return await asyncio.to_thread(_instagram_password_login, email, password)
    raise ValueError(f"Unknown platform: {platform}")


# --------------------------------------------------------------------
# Vault storage (encrypted at rest; status only is ever exposed)
# --------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def save_connector(platform: str, method: str, data: dict[str, Any]) -> None:
    """Encrypt and persist a verified connector credential blob."""
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")
    blob = {
        "method": method,
        "data": data,
        "connected_at": _now_iso(),
        "last_verified_at": _now_iso(),
    }
    connector_vault.set(PLATFORMS[platform]["vault_key"], json.dumps(blob), category="connector")
    log.info("connector_saved", platform=platform, method=method)


def load_connector(platform: str) -> dict[str, Any] | None:
    """Decrypt and return the stored credential blob (internal use only)."""
    raw = connector_vault.get(PLATFORMS[platform]["vault_key"])
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        log.error("connector_blob_corrupt", platform=platform)
        return None


def delete_connector(platform: str) -> bool:
    """Remove a connector's stored credentials."""
    ok = connector_vault.delete(PLATFORMS[platform]["vault_key"])
    if ok:
        log.info("connector_deleted", platform=platform)
    return ok


def connector_status(platform: str) -> dict[str, Any]:
    """
    Public status for one connector. Never includes secrets — only whether
    credentials exist, which auth method was used, and timestamps.
    """
    blob = load_connector(platform)
    if not blob:
        return {
            "id": platform,
            "name": PLATFORMS[platform]["name"],
            "connected": False,
            "auth_method": None,
            "connected_at": None,
            "last_verified_at": None,
        }
    return {
        "id": platform,
        "name": PLATFORMS[platform]["name"],
        "connected": True,
        "auth_method": blob.get("method"),
        "connected_at": blob.get("connected_at"),
        "last_verified_at": blob.get("last_verified_at"),
    }


def list_connector_status() -> list[dict[str, Any]]:
    """Public status for every supported connector."""
    return [connector_status(p) for p in PLATFORMS]
