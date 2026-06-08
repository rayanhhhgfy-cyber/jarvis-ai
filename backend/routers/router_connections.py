# ====================================================================
# JARVIS OMEGA — Connections Router
# ====================================================================
"""
API endpoints for managing integrations with Vercel, GitHub, Gmail, and Instagram.
Saves credentials securely into Secure Vault and performs real verification checks.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

from backend.vault.secure_vault import secure_vault
from shared.logger import get_logger

log = get_logger("router_connections")
router = APIRouter(prefix="/api/connections", tags=["Connections"])


class ConnectRequest(BaseModel):
    platform: str
    token: str


@router.get("/status")
async def get_connections_status() -> Dict[str, Any]:
    """Check connection status for Gmail, Instagram, GitHub, and Vercel."""
    status = {}

    # 1. GitHub
    github_token = secure_vault.retrieve("GITHUB_TOKEN")
    if github_token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github.v3+json",
                    }
                )
                if resp.status_code == 200:
                    user_data = resp.json()
                    status["github"] = {
                        "connected": True,
                        "username": user_data.get("login"),
                        "avatar_url": user_data.get("avatar_url"),
                    }
                else:
                    status["github"] = {"connected": False, "error": "Invalid GitHub Token"}
        except Exception as e:
            status["github"] = {"connected": False, "error": f"Failed to verify token: {e}"}
    else:
        status["github"] = {"connected": False}

    # 2. Vercel
    vercel_token = secure_vault.retrieve("VERCEL_TOKEN")
    if vercel_token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.vercel.com/v2/user",
                    headers={"Authorization": f"Bearer {vercel_token}"}
                )
                if resp.status_code == 200:
                    user_data = resp.json().get("user", {})
                    status["vercel"] = {
                        "connected": True,
                        "username": user_data.get("username"),
                        "email": user_data.get("email"),
                    }
                else:
                    status["vercel"] = {"connected": False, "error": "Invalid Vercel Token"}
        except Exception as e:
            status["vercel"] = {"connected": False, "error": f"Failed to verify token: {e}"}
    else:
        status["vercel"] = {"connected": False}

    # 3. Gmail
    gmail_token = secure_vault.retrieve("GMAIL_TOKEN") or secure_vault.retrieve("GMAIL_API_KEY")
    status["gmail"] = {"connected": bool(gmail_token)}

    # 4. Instagram
    insta_token = secure_vault.retrieve("INSTAGRAM_PASSWORD")
    status["instagram"] = {"connected": bool(insta_token)}

    # 5. Telegram
    telegram_token = secure_vault.retrieve("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{telegram_token}/getMe"
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    bot_data = resp.json().get("result", {})
                    status["telegram"] = {
                        "connected": True,
                        "username": bot_data.get("username"),
                    }
                else:
                    status["telegram"] = {"connected": False, "error": "Invalid Telegram Bot Token"}
        except Exception as e:
            status["telegram"] = {"connected": False, "error": f"Failed to verify: {e}"}
    else:
        status["telegram"] = {"connected": False}

    # 6. WhatsApp (browser-based, just check if flag is stored)
    wa_flag = secure_vault.retrieve("WHATSAPP_CONNECTED")
    status["whatsapp"] = {"connected": bool(wa_flag)}

    return status


@router.post("/connect")
async def connect_platform(req: ConnectRequest) -> Dict[str, Any]:
    """Save credentials to vault and verify them."""
    platform = req.platform.lower()
    token = req.token.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")

    if platform == "github":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github.v3+json",
                    }
                )
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail="Invalid GitHub Personal Access Token.")
                user_data = resp.json()
                secure_vault.store("GITHUB_TOKEN", token)
                return {"success": True, "username": user_data.get("login")}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"GitHub validation failed: {e}")

    elif platform == "vercel":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.vercel.com/v2/user",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail="Invalid Vercel Token.")
                user_data = resp.json().get("user", {})
                secure_vault.store("VERCEL_TOKEN", token)
                return {"success": True, "username": user_data.get("username")}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Vercel validation failed: {e}")

    elif platform == "gmail":
        secure_vault.store("GMAIL_TOKEN", token)
        return {"success": True}

    elif platform == "instagram":
        secure_vault.store("INSTAGRAM_PASSWORD", token)
        return {"success": True, "message": "Instagram token stored."}

    elif platform == "telegram":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{token}/getMe"
                )
                if resp.status_code != 200 or not resp.json().get("ok"):
                    raise HTTPException(status_code=400, detail="Invalid Telegram Bot Token.")
                bot_data = resp.json().get("result", {})
                secure_vault.store("TELEGRAM_BOT_TOKEN", token)
                return {"success": True, "username": bot_data.get("username")}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Telegram validation failed: {e}")

    elif platform == "whatsapp":
        secure_vault.store("WHATSAPP_CONNECTED", "true")
        return {"success": True, "message": "WhatsApp session flag stored. Use the browser to scan QR."}

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")


@router.post("/disconnect/{platform}")
async def disconnect_platform(platform: str) -> Dict[str, Any]:
    """Delete credentials from vault."""
    platform = platform.lower()
    if platform == "github":
        secure_vault.delete("GITHUB_TOKEN")
    elif platform == "vercel":
        secure_vault.delete("VERCEL_TOKEN")
    elif platform == "gmail":
        secure_vault.delete("GMAIL_TOKEN")
        secure_vault.delete("GMAIL_API_KEY")
    elif platform == "instagram":
        secure_vault.delete("INSTAGRAM_PASSWORD")
    elif platform == "telegram":
        secure_vault.delete("TELEGRAM_BOT_TOKEN")
    elif platform == "whatsapp":
        secure_vault.delete("WHATSAPP_CONNECTED")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    return {"success": True}


@router.post("/open-login/{platform}")
async def open_login_page(platform: str) -> Dict[str, Any]:
    """Direct Playwright to open the login page for a platform."""
    platform = platform.lower()
    from backend.services.social_reply_service import social_reply_service, PLATFORMS
    pconf = PLATFORMS.get(platform)
    if pconf:
        await social_reply_service._pw_call("navigate", {"url": pconf["url"]})
        return {"success": True, "message": f"{pconf['name']} page opened in Jarvis browser."}
    return {"success": False, "error": f"Platform login page not found: {platform}"}

