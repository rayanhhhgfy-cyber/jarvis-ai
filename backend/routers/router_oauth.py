# ====================================================================
# JARVIS OMEGA — OAuth callbacks
# ====================================================================
"""
OAuth callback endpoints. These are the redirect targets Sir's browser
lands on after he signs in with a provider:

  GET /api/oauth/google/callback?code=...&state=...
  GET /api/oauth/x/callback?code=...&state=...
  GET /api/oauth/tiktok/callback?code=...&state=...

The callback exchanges the code for tokens, stores them encrypted in
the vault, and shows a plain success page. Nothing here accepts a
password, and no token is ever shown on the page.

For X, the PKCE code_verifier is kept in a small JsonStore keyed by
the OAuth `state` value, written when the sign-in link is created
(/connect x) and consumed here.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.services import google_connector
from backend.services.dm_store import JsonStore
from shared.logger import get_logger

log = get_logger("router_oauth")

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

_oauth_states = JsonStore("oauth_states.json")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{title}</title></head>"
            "<body style='font-family:sans-serif;max-width:480px;margin:40px auto;"
            "padding:0 16px;color:#111'>"
            f"<h1>{title}</h1><p>{body}</p>"
            "</body></html>"
        )
    )


@router.get("/google/callback")
async def google_callback(request: Request) -> HTMLResponse:
    """Google OAuth redirect: exchange the code, store the refresh token."""
    code = request.query_params.get("code", "")
    error = request.query_params.get("error", "")
    if error:
        log.warning("google_oauth_callback_error", error=error)
        return _page(
            "Google connection failed",
            "Google said no. Go back to Telegram and send /connect google again.",
        )
    if not code:
        return _page(
            "Google connection failed",
            "No code came back from Google. Go back to Telegram and send /connect google again.",
        )
    result = await google_connector.exchange_code(code)
    if not result.get("ok"):
        log.warning("google_oauth_exchange_failed", error=str(result.get("error"))[:200])
        return _page(
            "Google connection failed",
            "I could not finish the sign-in. Go back to Telegram and send /connect google again.",
        )
    email = result.get("email") or "your Google account"
    return _page(
        "Google connected",
        f"Jarvis is now connected to {email}. You can close this page and go back to Telegram — try /gmail or /calendar.",
    )


def store_oauth_state(state: str, service: str, data: dict) -> None:
    """Keep the PKCE verifier (X) until the callback arrives."""
    _oauth_states.set(state, {"service": service, **data})


def _take_oauth_state(state: str) -> dict | None:
    """Read and delete a stored OAuth state (one-time use)."""
    saved = _oauth_states.get(state)
    if saved:
        _oauth_states.delete(state)
    return saved


@router.get("/x/callback")
async def x_callback(request: Request) -> HTMLResponse:
    """X OAuth redirect: exchange the code (PKCE), store the tokens."""
    from backend.services import x_connector

    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error", "")
    if error or not code:
        log.warning("x_oauth_callback_error", error=error)
        return _page(
            "X connection failed",
            "X said no. Go back to Telegram and send /connect x again.",
        )
    saved = _take_oauth_state(state) if state else None
    verifier = (saved or {}).get("code_verifier", "")
    if not verifier:
        return _page(
            "X connection failed",
            "I lost the sign-in session. Go back to Telegram and send /connect x again.",
        )
    result = await x_connector.exchange_code(
        code, verifier, "https://jarvis-ai-6c11.onrender.com/api/oauth/x/callback"
    )
    if not result.get("ok"):
        log.warning("x_oauth_exchange_failed", error=str(result.get("error"))[:200])
        return _page(
            "X connection failed",
            "I could not finish the sign-in. Go back to Telegram and send /connect x again.",
        )
    username = result.get("username") or "your X account"
    return _page(
        "X connected",
        f"Jarvis is now connected to @{username}. You can close this page and go back to Telegram — try /x.",
    )


@router.get("/tiktok/callback")
async def tiktok_callback(request: Request) -> HTMLResponse:
    """TikTok OAuth redirect: exchange the code, store the tokens."""
    from backend.services import tiktok_connector

    code = request.query_params.get("code", "")
    error = request.query_params.get("error", "")
    if error or not code:
        log.warning("tiktok_oauth_callback_error", error=error)
        return _page(
            "TikTok connection failed",
            "TikTok said no. Go back to Telegram and send /connect tiktok again.",
        )
    result = await tiktok_connector.exchange_code(
        code, "https://jarvis-ai-6c11.onrender.com/api/oauth/tiktok/callback"
    )
    if not result.get("ok"):
        log.warning("tiktok_oauth_exchange_failed", error=str(result.get("error"))[:200])
        return _page(
            "TikTok connection failed",
            "I could not finish the sign-in. Go back to Telegram and send /connect tiktok again.",
        )
    name = result.get("display_name") or result.get("open_id") or "your TikTok account"
    return _page(
        "TikTok connected",
        f"Jarvis is now connected to {name}. You can close this page and go back to Telegram — try /tiktok.",
    )
