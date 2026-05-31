# ====================================================================
# JARVIS OMEGA — Push Notification Engine
# ====================================================================
"""
Push notification engine supporting Web Push protocol (VAPID),
device-specific routing, notification dispatching, and alert history.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from pywebpush import webpush, WebPushException

from shared.logger import get_logger
from shared.models import Notification
from backend.config import settings

log = get_logger("notification_engine")


class NotificationEngine:
    """
    Manages push notification subscriptions, caches notification history,
    and dispatches Web Push notifications using VAPID keys.
    """

    def __init__(self, storage_dir: str = "./storage") -> None:
        self._subscriptions_path = Path(storage_dir) / "push_subscriptions.json"
        self._history_path = Path(storage_dir) / "notification_history.json"
        self._subscriptions: Dict[str, Dict[str, Any]] = {}  # device_id → subscription_info
        self._history: List[Notification] = []

    async def initialize(self) -> None:
        """Load subscriptions and notification history from disk."""
        if self._subscriptions_path.exists():
            try:
                self._subscriptions = json.loads(self._subscriptions_path.read_text(encoding="utf-8"))
                log.info("subscriptions_loaded", count=len(self._subscriptions))
            except Exception as e:
                log.error("subscriptions_load_error", error=str(e))

        if self._history_path.exists():
            try:
                history_data = json.loads(self._history_path.read_text(encoding="utf-8"))
                self._history = [Notification(**n) for n in history_data]
                log.info("notification_history_loaded", count=len(self._history))
            except Exception as e:
                log.error("notification_history_load_error", error=str(e))

    async def save_subscription(self, device_id: str, subscription_info: Dict[str, Any]) -> None:
        """Register or update a Web Push subscription for a device."""
        self._subscriptions[device_id] = subscription_info
        try:
            self._subscriptions_path.parent.mkdir(parents=True, exist_ok=True)
            self._subscriptions_path.write_text(json.dumps(self._subscriptions, indent=2), encoding="utf-8")
            log.info("subscription_saved", device_id=device_id)
        except Exception as e:
            log.error("subscription_save_failed", device_id=device_id, error=str(e))

    async def remove_subscription(self, device_id: str) -> None:
        """Remove a Web Push subscription for a device."""
        if device_id in self._subscriptions:
            self._subscriptions.pop(device_id)
            try:
                self._subscriptions_path.write_text(json.dumps(self._subscriptions, indent=2), encoding="utf-8")
                log.info("subscription_removed", device_id=device_id)
            except Exception as e:
                log.error("subscription_remove_failed", device_id=device_id, error=str(e))

    async def send_notification(self, notification: Notification) -> bool:
        """
        Deliver a push notification. Send to target devices if specified,
        otherwise broadcast to all registered devices.
        """
        # Save to history
        self._history.append(notification)
        await self._persist_history()

        devices_to_notify = notification.target_devices or list(self._subscriptions.keys())
        if not devices_to_notify:
            log.debug("no_devices_registered_for_push")
            return False

        payload_str = json.dumps({
            "notification_id": notification.notification_id,
            "title": notification.title,
            "body": notification.body,
            "icon": notification.icon,
            "category": notification.category,
            "action_url": notification.action_url,
            "data": notification.data,
            "timestamp": notification.created_at.isoformat(),
        })

        success_count = 0
        for device_id in devices_to_notify:
            sub = self._subscriptions.get(device_id)
            if not sub:
                continue

            try:
                # Use Web Push with VAPID configuration
                webpush(
                    subscription_info=sub,
                    data=payload_str,
                    vapid_private_key=settings.vapid_private_key or None,
                    vapid_claims={"sub": f"mailto:{settings.vapid_claims_email}"},
                )
                success_count += 1
                log.debug("push_delivered_success", device_id=device_id)
            except WebPushException as ex:
                log.error("webpush_exception", device_id=device_id, error=str(ex))
                # If subscription has expired or is invalid, remove it
                if ex.response is not None and ex.response.status_code in (404, 410):
                    log.warning("removing_expired_subscription", device_id=device_id)
                    await self.remove_subscription(device_id)
            except Exception as err:
                log.error("push_delivery_error", device_id=device_id, error=str(err))

        log.info(
            "notification_dispatched",
            title=notification.title,
            targets=len(devices_to_notify),
            delivered=success_count,
        )
        return success_count > 0

    async def get_history(self, limit: int = 50) -> List[Notification]:
        """Retrieve recent notification logs."""
        return self._history[-limit:]

    async def clear_history(self) -> None:
        """Clear cached notification history."""
        self._history.clear()
        await self._persist_history()

    async def _persist_history(self) -> None:
        """Save history logs to disk."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            data = [n.model_dump(mode="json") for n in self._history]
            self._history_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("history_persist_failed", error=str(e))


# Global notification engine instance
notification_engine = NotificationEngine()
