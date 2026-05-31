# ====================================================================
# JARVIS OMEGA — Approval Service
# ====================================================================
"""
Business logic service layer for human approvals. Assess risks and manages
approval requests, alerts, timeouts, and notification flows.
"""

from __future__ import annotations

from typing import List, Optional

from shared.models import ApprovalRequest
from shared.constants import RiskLevel
from backend.approval_gateway import approval_gateway
from backend.services.notification_service import notification_service
from shared.logger import get_logger

log = get_logger("approval_service")


class ApprovalService:
    """
    Orchestrates the approval request lifecycle: risk assessment,
    database/in-memory queue registration, and client push notification delivery.
    """

    async def create_request(
        self,
        action: str,
        reason: str,
        affected_resources: Optional[List[str]] = None,
        expected_result: str = "",
        undo_possible: bool = False,
        requesting_agent: str = "",
        task_id: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Creates and registers an approval request. Checks the action against risk definitions,
        saves it, and fires notifications to all connected devices.
        """
        # Determine risk level based on keyword heuristic
        risk_level = RiskLevel.MEDIUM
        action_lower = action.lower()
        if any(keyword in action_lower for keyword in ("rm", "delete", "destroy", "format", "shutdown", "kill")):
            risk_level = RiskLevel.CRITICAL
        elif any(keyword in action_lower for keyword in ("write", "modify", "install", "update", "run", "execute")):
            risk_level = RiskLevel.HIGH

        request = ApprovalRequest(
            action=action,
            reason=reason,
            risk_level=risk_level,
            affected_resources=affected_resources or [],
            expected_result=expected_result,
            undo_possible=undo_possible,
            requesting_agent=requesting_agent,
            task_id=task_id,
        )

        # Register in gateway
        await approval_gateway.request_approval(request)

        # Send push notifications via Web Push
        try:
            await notification_service.send_approval_request(
                approval_id=request.approval_id,
                action=action,
                reason=reason,
            )
        except Exception as e:
            log.error("approval_push_notification_failed", approval_id=request.approval_id, error=str(e))

        return request

    async def check_and_execute_approval(self, approval_id: str, timeout: float = 300.0) -> bool:
        """
        Blocks execution of an agent action until Sir approves or rejects,
        or a timeout threshold is exceeded.
        """
        return await approval_gateway.wait_for_approval(approval_id, timeout=timeout)

    def get_pending_requests(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        return approval_gateway.get_pending()

    def get_history(self, limit: int = 50) -> List[ApprovalRequest]:
        """Get past approval decisions."""
        return approval_gateway.get_history(limit=limit)


# Global approval service instance
approval_service = ApprovalService()
