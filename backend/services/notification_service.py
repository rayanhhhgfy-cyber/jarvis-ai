# ====================================================================
# JARVIS OMEGA — Notification Service
# ====================================================================
"""
Service layer for push notifications. Provides structured entry points
for sending alerts, approvals, tasks, and system events to Sir's devices.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional

from shared.models import Notification
from shared.constants import TaskPriority
from backend.notification_engine import notification_engine
from shared.logger import get_logger

log = get_logger("notification_service")


class NotificationService:
    """
    Business logic layer for generating and dispatching notifications.
    Supports system alerts, approvals, and general notifications.
    """

    async def send_system_alert(
        self,
        title: str,
        body: str,
        priority: TaskPriority = TaskPriority.HIGH,
        target_devices: Optional[List[str]] = None,
    ) -> bool:
        """Dispatch a critical system alert notification."""
        notif = Notification(
            title=title,
            body=body,
            category="system_alert",
            priority=priority,
            icon="alert-octagon",
            target_devices=target_devices or [],
        )
        return await notification_engine.send_notification(notif)

    async def send_approval_request(
        self,
        approval_id: str,
        action: str,
        reason: str,
        target_devices: Optional[List[str]] = None,
    ) -> bool:
        """Notify Sir that a dangerous operation is waiting for approval."""
        notif = Notification(
            title="Approval Required",
            body=f"Action: {action}. Reason: {reason}",
            category="approval_request",
            priority=TaskPriority.CRITICAL,
            icon="shield-alert",
            target_devices=target_devices or [],
            action_url=f"/approvals?id={approval_id}",
            data={"approval_id": approval_id, "action": action},
        )
        return await notification_engine.send_notification(notif)

    async def send_task_update(
        self,
        task_id: str,
        title: str,
        status_str: str,
        body: str = "",
        target_devices: Optional[List[str]] = None,
    ) -> bool:
        """Send task progress updates."""
        notif = Notification(
            title=f"Task: {title}",
            body=body or f"Status updated to: {status_str}",
            category="task_update",
            priority=TaskPriority.MEDIUM,
            icon="check-circle",
            target_devices=target_devices or [],
            action_url=f"/tasks?id={task_id}",
            data={"task_id": task_id, "status": status_str},
        )
        return await notification_engine.send_notification(notif)

    async def send_general_message(
        self,
        title: str,
        body: str,
        target_devices: Optional[List[str]] = None,
    ) -> bool:
        """Send general update messages to devices."""
        notif = Notification(
            title=title,
            body=body,
            category="general",
            priority=TaskPriority.LOW,
            icon="message-square",
            target_devices=target_devices or [],
        )
        return await notification_engine.send_notification(notif)


# Global notification service instance
notification_service = NotificationService()
