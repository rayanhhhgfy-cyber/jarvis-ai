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


# Turso mirror for push subscriptions: Render's disk is ephemeral, so a
# subscription saved only to ./storage is wiped on every deploy and the
# next /call goes to zero devices. Turso survives redeploys. The mirror
# is best-effort (a failure is logged, the local file still holds the
# write) and uses a short timeout so it never stalls a send.
_TURSO_TABLE = "push_subscriptions"
_TURSO_TIMEOUT = 5.0
# Test hook: tests set this to a mock httpx transport.
_test_turso_transport: Any | None = None
_turso_client: Any | None = None
_turso_attempted = False
_turso_table_ready = False


def _turso_store() -> Any | None:
    """A Turso store for push subscriptions, or None when unconfigured."""
    global _turso_client, _turso_attempted
    if _turso_attempted:
        return _turso_client
    _turso_attempted = True
    try:
        from backend.services.credentials_vault import _TursoStore

        url = settings.turso_database_url
        token = settings.turso_auth_token
        if url and token:
            _turso_client = _TursoStore(
                url, token, _TURSO_TABLE,
                transport=_test_turso_transport,
                timeout=_TURSO_TIMEOUT,
            )
    except (ImportError, ValueError) as e:
        log.warning("push_turso_unavailable", error=str(e))
        _turso_client = None
    return _turso_client


def _turso_ensure_table(client: Any) -> None:
    """Create the subscriptions table once per process."""
    global _turso_table_ready
    if _turso_table_ready:
        return
    client.ensure_table()
    _turso_table_ready = True


def derive_vapid_public_key(private_key_b64: str) -> str | None:
    """Derive the VAPID public key (base64url uncompressed point) from the private key.

    The server signs pushes with the private key, so the public key the
    app subscribes with MUST be the one matching it. Deriving it here
    makes a configured-public/private mismatch impossible: the endpoint
    serves the derived key, never a stale configured copy.
    """
    try:
        import base64

        from cryptography.hazmat.primitives.asymmetric import ec

        raw = base64.urlsafe_b64decode(private_key_b64 + "=" * (-len(private_key_b64) % 4))
        if len(raw) != 32:
            return None
        priv = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
        nums = priv.public_key().public_numbers()
        point = b"\x04" + nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
        return base64.urlsafe_b64encode(point).decode().rstrip("=")
    except (ValueError, TypeError):
        # Bad base64, wrong length handled above, or scalar out of range.
        # Callers log the failure (router + engine startup check).
        return None


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
        # VAPID self-check: the public key the app subscribes with must
        # be the one matching the private key we sign with. Log it once
        # at startup so a mismatch is visible in the logs, not just as
        # a BadJwtToken from the push service later.
        if settings.vapid_private_key:
            derived = derive_vapid_public_key(settings.vapid_private_key)
            if derived is None:
                log.error("vapid_private_key_invalid_cannot_derive_public_key")
            elif derived != (settings.vapid_public_key or ""):
                log.warning(
                    "vapid_public_key_mismatch",
                    configured_prefix=(settings.vapid_public_key or "")[:12],
                    derived_prefix=derived[:12],
                )
            else:
                log.info("vapid_keypair_match", public_prefix=derived[:12])
        if self._subscriptions_path.exists():
            try:
                self._subscriptions = json.loads(self._subscriptions_path.read_text(encoding="utf-8"))
                log.info("subscriptions_loaded", count=len(self._subscriptions))
            except Exception as e:
                log.error("subscriptions_load_error", error=str(e))
        else:
            # No local file (fresh deploy wiped it): restore from Turso,
            # the copy that survives redeploys.
            restored = self._load_turso()
            if restored:
                self._subscriptions = restored
                log.info("subscriptions_restored_turso", count=len(restored))
                try:
                    self._subscriptions_path.parent.mkdir(parents=True, exist_ok=True)
                    self._subscriptions_path.write_text(
                        json.dumps(self._subscriptions, indent=2), encoding="utf-8"
                    )
                except Exception as e:
                    log.error("subscriptions_restore_save_failed", error=str(e))

        if self._history_path.exists():
            try:
                history_data = json.loads(self._history_path.read_text(encoding="utf-8"))
                self._history = [Notification(**n) for n in history_data]
                log.info("notification_history_loaded", count=len(self._history))
            except Exception as e:
                log.error("notification_history_load_error", error=str(e))

    def _load_turso(self) -> dict[str, Any] | None:
        """Load subscriptions from Turso, or None when unavailable."""
        client = _turso_store()
        if client is None:
            return None
        try:
            _turso_ensure_table(client)
            return dict(client.load_all())
        except (RuntimeError, ValueError) as e:
            log.warning("push_turso_load_failed", error=str(e))
            return None

    def _sync_turso(self) -> None:
        """Best-effort mirror of all subscriptions to Turso."""
        client = _turso_store()
        if client is None:
            return
        try:
            _turso_ensure_table(client)
            client.save_all(self._subscriptions)
        except (RuntimeError, TypeError, ValueError) as e:
            # Best-effort only: the local file already holds the write,
            # and the next save re-syncs the full set.
            log.warning("push_turso_save_failed", error=str(e))

    def subscription_count(self) -> int:
        """How many devices are currently subscribed."""
        return len(self._subscriptions)

    def subscription_device_ids(self) -> list[str]:
        """The device ids currently subscribed."""
        return list(self._subscriptions.keys())

    async def save_subscription(self, device_id: str, subscription_info: Dict[str, Any]) -> None:
        """Register or update a Web Push subscription for a device."""
        self._subscriptions[device_id] = subscription_info
        try:
            self._subscriptions_path.parent.mkdir(parents=True, exist_ok=True)
            self._subscriptions_path.write_text(json.dumps(self._subscriptions, indent=2), encoding="utf-8")
            log.info("subscription_saved", device_id=device_id)
        except Exception as e:
            log.error("subscription_save_failed", device_id=device_id, error=str(e))
        self._sync_turso()

    async def remove_subscription(self, device_id: str) -> None:
        """Remove a Web Push subscription for a device."""
        if device_id in self._subscriptions:
            self._subscriptions.pop(device_id)
            try:
                self._subscriptions_path.write_text(json.dumps(self._subscriptions, indent=2), encoding="utf-8")
                log.info("subscription_removed", device_id=device_id)
            except Exception as e:
                log.error("subscription_remove_failed", device_id=device_id, error=str(e))
            self._sync_turso()

    async def send_notification(self, notification: Notification) -> bool:
        """
        Deliver a push notification. Send to target devices if specified,
        otherwise broadcast to all registered devices.
        """
        # Save to history
        self._history.append(notification)
        await self._persist_history()

        # Chat-controlled mute (backend/services/system_toggles.py):
        # while muted, pushes are logged in history but never delivered.
        # Imported lazily to avoid an import cycle with system_toggles.
        try:
            from backend.services.system_toggles import is_notifications_muted

            if is_notifications_muted():
                log.info("push_muted_skipping_delivery", title=notification.title)
                return False
        except (ImportError, AttributeError) as mute_err:
            log.debug("push_mute_check_failed", error=str(mute_err))

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
