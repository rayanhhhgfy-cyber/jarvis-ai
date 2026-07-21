# ====================================================================
# JARVIS OMEGA — Approval Gateway Tests
# ====================================================================
"""
Phase 1 regression tests for the human-in-the-loop approval gateway.

Verifies request lifecycle: create -> wait -> approve/reject -> timeout.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.approval_gateway import ApprovalGateway
from shared.constants import RiskLevel
from shared.models import ApprovalRequest


def _make_request(action: str = "delete_project") -> ApprovalRequest:
    return ApprovalRequest(
        action=action,
        reason="Unit test",
        risk_level=RiskLevel.HIGH,
        affected_resources=["./workspace/foo"],
        expected_result="directory removed",
        undo_possible=False,
        requesting_agent="test",
    )


@pytest.mark.asyncio
async def test_request_and_approve():
    gw = ApprovalGateway()
    req = _make_request()
    approval_id = await gw.request_approval(req)
    assert approval_id == req.approval_id
    assert gw.get_pending()[0].approval_id == approval_id

    # Schedule the approval to fire immediately so wait_for_approval returns True.
    async def _approve():
        await asyncio.sleep(0.01)
        assert await gw.approve(approval_id)

    asyncio.create_task(_approve())
    result = await gw.wait_for_approval(approval_id, timeout=1.0)
    assert result is True
    assert gw.get_pending() == []


@pytest.mark.asyncio
async def test_request_and_reject():
    gw = ApprovalGateway()
    req = _make_request()
    approval_id = await gw.request_approval(req)

    async def _reject():
        await asyncio.sleep(0.01)
        assert await gw.reject(approval_id, reason="nope")

    asyncio.create_task(_reject())
    result = await gw.wait_for_approval(approval_id, timeout=1.0)
    assert result is False


@pytest.mark.asyncio
async def test_request_timeout():
    """A request with no response should time out and return False."""
    gw = ApprovalGateway()
    req = _make_request()
    approval_id = await gw.request_approval(req)
    result = await gw.wait_for_approval(approval_id, timeout=0.05)
    assert result is False


def test_is_dangerous_matches_dangerous_actions():
    """The existing string-match API still works for ``DANGEROUS_ACTIONS``."""
    gw = ApprovalGateway()
    assert gw.is_dangerous("delete_project") is True
    assert gw.is_dangerous("format_drive") is True
    assert gw.is_dangerous("read_file") is False


@pytest.mark.asyncio
async def test_approve_unknown_id_returns_false():
    gw = ApprovalGateway()
    assert await gw.approve("does-not-exist") is False
    assert await gw.reject("does-not-exist") is False
