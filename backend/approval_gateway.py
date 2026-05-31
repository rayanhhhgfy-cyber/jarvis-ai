# ====================================================================
# JARVIS OMEGA — Approval Gateway
# ====================================================================
"""
Human Approval Gateway: risk assessment, approval request creation,
notification to Sir, and approve/reject flow. No critical action
executes before Sir's explicit approval.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from shared.constants import DANGEROUS_ACTIONS, EventType, RiskLevel
from shared.logger import get_logger
from shared.models import ApprovalRequest

log = get_logger("approval_gateway")


class ApprovalGateway:
    """
    Controls dangerous action execution.
    All critical operations must pass through here.
    """

    def __init__(self) -> None:
        self._pending: Dict[str, ApprovalRequest] = {}
        self._history: List[ApprovalRequest] = []
        self._event_bus = None
        self._ws_manager = None
        self._waiters: Dict[str, asyncio.Event] = {}

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    def set_ws_manager(self, ws_manager: Any) -> None:
        self._ws_manager = ws_manager

    def is_dangerous(self, action: str) -> bool:
        """Check if an action requires approval."""
        return action in DANGEROUS_ACTIONS

    async def request_approval(self, request: ApprovalRequest) -> str:
        """
        Submit an approval request. Returns the approval_id.
        The requesting agent must wait for Sir's response.
        """
        self._pending[request.approval_id] = request
        self._waiters[request.approval_id] = asyncio.Event()

        log.warning(
            "approval_requested",
            approval_id=request.approval_id,
            action=request.action,
            risk_level=request.risk_level.value,
            reason=request.reason,
        )

        # Notify Sir via event bus and WebSocket
        if self._event_bus:
            await self._event_bus.publish(
                EventType.APPROVAL_REQUESTED,
                {
                    "approval_id": request.approval_id,
                    "action": request.action,
                    "reason": request.reason,
                    "risk_level": request.risk_level.value,
                    "affected_resources": request.affected_resources,
                    "expected_result": request.expected_result,
                    "undo_possible": request.undo_possible,
                    "requesting_agent": request.requesting_agent,
                },
            )

        if self._ws_manager:
            await self._ws_manager.broadcast({
                "type": "approval_request",
                "payload": request.model_dump(mode="json"),
            })

        return request.approval_id

    async def wait_for_approval(self, approval_id: str, timeout: float = 300.0) -> bool:
        """
        Block until Sir approves or rejects, or timeout.
        Returns True if approved, False otherwise.
        """
        waiter = self._waiters.get(approval_id)
        if not waiter:
            return False

        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout)
            request = self._pending.get(approval_id)
            return request.approved if request else False
        except asyncio.TimeoutError:
            log.warning("approval_timeout", approval_id=approval_id)
            await self.reject(approval_id, reason="Timeout — no response from Sir")
            return False

    async def approve(self, approval_id: str) -> bool:
        """Sir approves a pending request."""
        request = self._pending.get(approval_id)
        if not request:
            return False

        request.approved = True
        request.approved_at = datetime.utcnow()
        request.approved_by = "Sir"

        # Signal the waiting agent
        waiter = self._waiters.get(approval_id)
        if waiter:
            waiter.set()

        self._history.append(request)
        self._pending.pop(approval_id, None)

        log.info("approval_granted", approval_id=approval_id, action=request.action)

        if self._event_bus:
            await self._event_bus.publish(
                EventType.APPROVAL_GRANTED,
                {"approval_id": approval_id, "action": request.action},
            )

        return True

    async def reject(self, approval_id: str, reason: str = "") -> bool:
        """Sir rejects a pending request."""
        request = self._pending.get(approval_id)
        if not request:
            return False

        request.approved = False
        request.approved_at = datetime.utcnow()
        request.approved_by = "Sir"

        waiter = self._waiters.get(approval_id)
        if waiter:
            waiter.set()

        self._history.append(request)
        self._pending.pop(approval_id, None)

        log.info("approval_denied", approval_id=approval_id, reason=reason)

        if self._event_bus:
            await self._event_bus.publish(
                EventType.APPROVAL_DENIED,
                {"approval_id": approval_id, "action": request.action, "reason": reason},
            )

        return True

    def get_pending(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        return list(self._pending.values())

    def get_history(self, limit: int = 50) -> List[ApprovalRequest]:
        """Get approval history."""
        return self._history[-limit:]


# Global approval gateway instance
approval_gateway = ApprovalGateway()
