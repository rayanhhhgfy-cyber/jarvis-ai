# ====================================================================
# JARVIS OMEGA — Web Push Notifications Router
# ====================================================================
"""
REST endpoints for Web Push (VAPID) subscriptions.

The frontend PWA registers its push subscription here; Jarvis sends a
push whenever something needs Sir's attention (a DM was answered, a
task finished). The VAPID *public* key is public by design and is
served to the frontend so it can subscribe. The VAPID *private* key
never leaves the server (env var VAPID_PRIVATE_KEY).

iOS note: web push on iPhone only works when the PWA has been added to
the Home Screen (iOS 16.4+). Until then, subscribing will fail and the
endpoint reports that plainly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from backend.config import settings
from backend.notification_engine import derive_vapid_public_key, notification_engine
from shared.logger import get_logger
from shared.models import Notification

log = get_logger("router_notifications")
router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


# --------------------------------------------------------------------
# Models
# --------------------------------------------------------------------

class PushSubscribeRequest(BaseModel):
    device_id: str = Field(..., description="Stable device id, e.g. the PWA install id.")
    subscription: dict[str, Any] = Field(..., description="PushSubscription JSON from the browser.")


class PushSendRequest(BaseModel):
    title: str = Field(..., description="Notification title.")
    body: str = Field(..., description="Notification body.")
    category: str = Field("general", description="Category label.")
    action_url: str | None = Field(None, description="URL opened when the notification is tapped.")
    target_devices: list[str] = Field(default_factory=list, description="Device ids; empty = all.")


# --------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------

@router.get("/vapid-public-key")
async def get_vapid_public_key(response: Response) -> dict[str, Any]:
    """The VAPID public key (safe to expose — it is not a secret).

    Serves the key DERIVED from the configured private key, so the key
    the app subscribes with always matches the key the server signs
    with — a stale configured public key can never cause BadJwtToken.
    Marked no-store: browsers must never cache this response, or a
    subscription made after a key rotation would be bound to the old key.
    """
    response.headers["Cache-Control"] = "no-store"
    public_key = settings.vapid_public_key or ""
    if settings.vapid_private_key:
        derived = derive_vapid_public_key(settings.vapid_private_key)
        if derived:
            if derived != public_key:
                log.warning(
                    "vapid_public_key_mismatch_serving_derived",
                    configured_prefix=public_key[:12] if public_key else "",
                    derived_prefix=derived[:12],
                )
            public_key = derived
        else:
            log.error("vapid_private_key_invalid_cannot_derive_public_key")
    return {
        "public_key": public_key,
        "configured": bool(public_key and settings.vapid_private_key),
    }


@router.post("/subscribe")
async def subscribe_push(req: PushSubscribeRequest) -> dict[str, Any]:
    """Save (or refresh) a Web Push subscription for a device."""
    sub = req.subscription or {}
    if not sub.get("endpoint") or not isinstance(sub.get("keys"), dict):
        raise HTTPException(
            status_code=422,
            detail="Invalid push subscription: expected endpoint + keys.",
        )
    await notification_engine.save_subscription(req.device_id, sub)
    log.info("push_subscribed", device_id=req.device_id)
    return {"subscribed": True, "device_id": req.device_id}


@router.post("/unsubscribe")
async def unsubscribe_push(req: PushSubscribeRequest) -> dict[str, Any]:
    """Remove a Web Push subscription."""
    await notification_engine.remove_subscription(req.device_id)
    return {"subscribed": False, "device_id": req.device_id}


@router.post("/send")
async def send_push(req: PushSendRequest) -> dict[str, Any]:
    """Send a push notification now (used by Jarvis + the dashboard test button)."""
    if not settings.vapid_private_key:
        raise HTTPException(
            status_code=503,
            detail="VAPID_PRIVATE_KEY is not set. Generate VAPID keys and set "
                   "VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY in the environment.",
        )
    sent = await notification_engine.send_notification(Notification(
        title=req.title,
        body=req.body,
        category=req.category,
        action_url=req.action_url,
        target_devices=req.target_devices,
    ))
    return {"sent": bool(sent)}


@router.get("/status")
async def push_status() -> dict[str, Any]:
    """One-call diagnostic for push health.

    Returns how many devices are subscribed (and which), plus the
    VAPID public-key prefix the server is serving, so a failed call
    can be diagnosed without reading Render logs: zero subscriptions
    means the device must tap "enable notifications" again; a key
    prefix that does not match the one the app subscribed with means
    a key rotation happened after the subscription.
    """
    public_key = settings.vapid_public_key or ""
    if settings.vapid_private_key:
        derived = derive_vapid_public_key(settings.vapid_private_key)
        if derived:
            public_key = derived
    return {
        "subscriptions": notification_engine.subscription_count(),
        "devices": notification_engine.subscription_device_ids(),
        "public_key_prefix": public_key[:12] if public_key else "",
        "configured": bool(public_key and settings.vapid_private_key),
    }


@router.get("/history")
async def push_history(limit: int = 50) -> list[dict[str, Any]]:
    """Recent push notifications Jarvis sent."""
    history = await notification_engine.get_history(limit=limit)
    return [n.model_dump(mode="json") for n in history]
