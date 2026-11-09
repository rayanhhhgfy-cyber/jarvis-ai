# ====================================================================
# JARVIS OMEGA — DM Connectors Router
# ====================================================================
"""
REST endpoints for the dashboard Connectors tab (Messenger + Instagram).

Sir pastes EITHER an email+password pair OR a cookies export. The login
is verified BEFORE anything is stored; verified credentials are stored
encrypted in the connector vault. The API NEVER returns a secret — only
connected/disconnected status, the auth method, and timestamps.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services import dm_auth
from backend.services.dm_responder import dm_responder
from shared.logger import get_logger

log = get_logger("router_connectors")
router = APIRouter(prefix="/api/connectors", tags=["Connectors"])


# --------------------------------------------------------------------
# Models
# --------------------------------------------------------------------

class ConnectorConnectRequest(BaseModel):
    """One complete auth form — exactly one of the two."""

    method: str = Field(..., description="'cookies' or 'password'.")
    email: str | None = Field(None, description="Account email/username (password form).")
    password: str | None = Field(None, description="Account password (password form).")
    cookies: str | None = Field(None, description="Pasted cookies (cookies form).")


# --------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------

@router.get("")
async def list_connectors() -> dict[str, Any]:
    """List Messenger + Instagram with status only (never secrets)."""
    return {
        "connectors": dm_auth.list_connector_status(),
        "responder": dm_responder.get_status(),
    }


@router.get("/{connector_id}/status")
async def get_connector_status(connector_id: str) -> dict[str, Any]:
    """Status for one connector, plus the responder state for it."""
    if connector_id not in dm_auth.PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'")
    status = dm_auth.connector_status(connector_id)
    status["responder"] = dm_responder.get_status()["platforms"][connector_id]
    return status


@router.post("/{connector_id}/connect")
async def connect_connector(connector_id: str, req: ConnectorConnectRequest) -> dict[str, Any]:
    """
    Connect a platform with EITHER cookies OR email+password.

    The login is verified first; only a verified login is stored
    (encrypted). A failed or challenged login stores nothing.
    """
    if connector_id not in dm_auth.PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'")

    # ---- Validate: exactly one complete form ----
    if req.method == "cookies":
        if req.email or req.password:
            raise HTTPException(
                status_code=422,
                detail="Cookies form must not include email/password.",
            )
        if not req.cookies or not req.cookies.strip():
            raise HTTPException(status_code=422, detail="Paste the cookies first.")
        try:
            cookies = dm_auth.parse_cookies(req.cookies)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        verified = await dm_auth.verify_cookies(connector_id, cookies)
        if not verified:
            raise HTTPException(
                status_code=502,
                detail="The cookies did not produce a logged-in session. "
                       "Copy fresh cookies from a logged-in browser tab and try again.",
            )
        dm_auth.save_connector(connector_id, "cookies", {"cookies": cookies})
        log.info("connector_connected", platform=connector_id, method="cookies")

    elif req.method == "password":
        if req.cookies:
            raise HTTPException(
                status_code=422,
                detail="Password form must not include cookies.",
            )
        if not req.email or not req.email.strip() or not req.password:
            raise HTTPException(
                status_code=422,
                detail="Enter both the email/username and the password.",
            )
        try:
            session_cookies = await dm_auth.login_with_password(
                connector_id, req.email.strip(), req.password
            )
        except dm_auth.LoginChallenge as e:
            raise HTTPException(status_code=428, detail=str(e))
        except dm_auth.LoginUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        except dm_auth.LoginFailed as e:
            raise HTTPException(status_code=502, detail=str(e))
        dm_auth.save_connector(connector_id, "password", {
            "email": req.email.strip(),
            "password": req.password,
            "cookies": session_cookies,
        })
        log.info("connector_connected", platform=connector_id, method="password")

    else:
        raise HTTPException(
            status_code=422,
            detail="method must be 'cookies' or 'password'.",
        )

    # A fresh connection must wake the responder: it only starts at boot,
    # and at boot there may have been no connector yet. start() is a
    # no-op when disabled or already running, so this is safe to call on
    # every connect. A failure here must never fail the connect itself.
    try:
        await dm_responder.start()
    except Exception as start_err:
        log.warning("dm_responder_start_after_connect_failed", error=str(start_err))

    return dm_auth.connector_status(connector_id)


@router.post("/{connector_id}/disconnect")
async def disconnect_connector(connector_id: str) -> dict[str, Any]:
    """Remove a connector's stored credentials."""
    if connector_id not in dm_auth.PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'")
    if not dm_auth.delete_connector(connector_id):
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' is not connected")
    log.info("connector_disconnected", platform=connector_id)
    return dm_auth.connector_status(connector_id)
