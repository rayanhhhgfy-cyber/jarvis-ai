# ====================================================================
# JARVIS OMEGA — Atxp Agent-Wallet Plugin
# ====================================================================
"""
Phase 8 paid-API plugin: wraps the atxp agent-wallet skill so JARVIS can
use 100+ paid models and external APIs (web search, image/video/music
generation, X/Twitter search, email send/receive, SMS, voice calls, etc.).

The wallet identifier + API token are stored in the credentials vault under
``atxp_wallet_id`` and ``atxp_api_token``. Sir funds the wallet via Stripe
or USDC out-of-band (see the atxp skill docs).

If atxp is not configured, every tool returns a helpful "not configured"
response rather than raising.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.tools import tool, RiskTier


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


def _configured() -> bool:
    return bool(_cred("atxp_wallet_id") and _cred("atxp_api_token"))


def _not_configured(tool_name: str) -> Dict[str, Any]:
    return {
        "configured": False,
        "error": (
            f"atxp is not configured. Open Settings → Credentials and add "
            f"'atxp_wallet_id' and 'atxp_api_token'. Fund the wallet via "
            f"Stripe or USDC through the atxp dashboard."
        ),
        "tool": tool_name,
    }


async def _atxp_post(path: str, payload: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    """POST to the atxp endpoint with the stored wallet credentials."""
    import httpx
    wallet = _cred("atxp_wallet_id")
    token = _cred("atxp_api_token")
    base = _cred("atxp_base_url") or "https://api.atxp.dev/v1"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base.rstrip('/')}/{path.lstrip('/')}",
            json={"wallet_id": wallet, **payload},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "JARVIS-OMEGA/1.0",
            },
        )
    if resp.status_code >= 400:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
    return {"ok": True, "data": resp.json()}


# --------------------------------------------------------------------
# Wallet
# --------------------------------------------------------------------

@tool(
    name="atxp.wallet_balance",
    description="Return the current atxp wallet balance (USD credit).",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="atxp",
)
async def atxp_wallet_balance() -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.wallet_balance")
    return await _atxp_post("/wallet/balance", {})


# --------------------------------------------------------------------
# AI generation
# --------------------------------------------------------------------

@tool(
    name="atxp.image_gen",
    description="Generate an image via atxp (FLUX / DALL-E / Imagen / SDXL — model chosen by atxp).",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "default": "flux-1.1-pro"},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_image_gen(prompt: str, model: str = "flux-1.1-pro") -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.image_gen")
    return await _atxp_post("/media/image", {"prompt": prompt, "model": model}, timeout=180)


@tool(
    name="atxp.video_gen",
    description="Generate a short video via atxp (Runway / Pika / Luma).",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "seconds": {"type": "number", "default": 5},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_video_gen(prompt: str, seconds: float = 5) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.video_gen")
    return await _atxp_post("/media/video", {"prompt": prompt, "seconds": seconds}, timeout=600)


@tool(
    name="atxp.music_gen",
    description="Generate a music track via atxp (Suno / Udio).",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "duration_seconds": {"type": "number", "default": 30},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_music_gen(prompt: str, duration_seconds: float = 30) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.music_gen")
    return await _atxp_post("/media/music", {"prompt": prompt, "duration": duration_seconds}, timeout=600)


# --------------------------------------------------------------------
# Communication
# --------------------------------------------------------------------

@tool(
    name="atxp.email_send",
    description="Send an email via the atxp email endpoint.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_email_send(to: str, subject: str, body: str) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.email_send")
    return await _atxp_post("/email/send", {"to": to, "subject": subject, "body": body})


@tool(
    name="atxp.sms_send",
    description="Send an SMS via atxp.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "E.164 phone number (e.g. +15551234567)."},
            "body": {"type": "string"},
        },
        "required": ["to", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_sms_send(to: str, body: str) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.sms_send")
    return await _atxp_post("/sms/send", {"to": to, "body": body})


@tool(
    name="atxp.voice_call",
    description="Place an AI-driven voice call via atxp.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "script": {"type": "string"},
            "voice": {"type": "string", "default": "en-US-Standard-A"},
        },
        "required": ["to", "script"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_voice_call(to: str, script: str, voice: str = "en-US-Standard-A") -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.voice_call")
    return await _atxp_post("/voice/call", {"to": to, "script": script, "voice": voice})


# --------------------------------------------------------------------
# Social / Search
# --------------------------------------------------------------------

@tool(
    name="atxp.x_search",
    description="Search X (Twitter) via atxp.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_x_search(query: str, limit: int = 20) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.x_search")
    return await _atxp_post("/x/search", {"query": query, "limit": limit})


# --------------------------------------------------------------------
# 100+ LLMs
# --------------------------------------------------------------------

@tool(
    name="atxp.llm_complete",
    description="Call any of the 100+ LLM models available via atxp.",
    parameters={
        "type": "object",
        "properties": {
            "model": {"type": "string", "description": "e.g. anthropic/claude-3.5-sonnet, openai/gpt-4o"},
            "prompt": {"type": "string"},
            "system": {"type": "string", "default": ""},
            "max_tokens": {"type": "integer", "default": 1024},
        },
        "required": ["model", "prompt"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="atxp",
)
async def atxp_llm_complete(model: str, prompt: str, system: str = "", max_tokens: int = 1024) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("atxp.llm_complete")
    return await _atxp_post(
        "/llm/complete",
        {"model": model, "prompt": prompt, "system": system, "max_tokens": max_tokens},
    )


PLUGIN_NAME = "atxp"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Atxp agent-wallet bridge — 100+ LLMs + paid APIs (image/video/music/email/SMS/voice/X search)."
