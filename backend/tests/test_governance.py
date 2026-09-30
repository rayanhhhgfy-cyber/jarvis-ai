# ====================================================================
# JARVIS OMEGA — Test Decision Governance Layer (Phase 2)
# ====================================================================

import pytest
from backend.governance import governance_layer, GovernanceReviewRequest
from shared.models import ApprovalRequest
from shared.constants import RiskLevel
from backend.approval_gateway import approval_gateway


@pytest.mark.asyncio
async def test_governance_red_team_veto():
    req = GovernanceReviewRequest(
        decision_type="strategy_change",
        action="Deploy marketing scheme with guaranteed profit",
    )
    res = await governance_layer.evaluate_decision(req)
    assert res["approved"] is False
    assert "red_team" in res["veto"]["vetoed_by"]


@pytest.mark.asyncio
async def test_governance_compliance_veto():
    req = GovernanceReviewRequest(
        decision_type="marketing",
        action="Send blast",
        channel="whatsapp",
        details={"broadcast_count": 5000},
    )
    res = await governance_layer.evaluate_decision(req)
    assert res["approved"] is False
    assert "compliance" in res["veto"]["vetoed_by"]


@pytest.mark.asyncio
async def test_governance_financial_veto():
    req = GovernanceReviewRequest(
        decision_type="ad_spend",
        action="Run Facebook Ads",
        amount_usd=500.0,  # Exceeds $50 daily cap default
    )
    res = await governance_layer.evaluate_decision(req)
    assert res["approved"] is False
    assert "financial" in res["veto"]["vetoed_by"]


@pytest.mark.asyncio
async def test_governance_risk_brand_veto():
    req = GovernanceReviewRequest(
        decision_type="new_business",
        action="Launch clickbait_fraud product",
    )
    res = await governance_layer.evaluate_decision(req)
    assert res["approved"] is False
    assert "risk_brand" in res["veto"]["vetoed_by"]


@pytest.mark.asyncio
async def test_governance_all_approve():
    req = GovernanceReviewRequest(
        decision_type="new_business",
        action="Launch AI Design Studio",
        amount_usd=10.0,
        channel="web",
        target_market="Jordan SMEs",
        details={"opt_out_link": True, "has_ftc_disclosure": True},
    )
    res = await governance_layer.evaluate_decision(req)
    assert res["approved"] is True


@pytest.mark.asyncio
async def test_approval_gateway_governance_veto_integration():
    req = ApprovalRequest(
        action="Launch clickbait_fraud campaign",
        reason="Test governance gate",
        risk_level=RiskLevel.HIGH,
    )
    app_id = await approval_gateway.request_approval(req)
    assert app_id == req.approval_id
    # Should be auto-rejected in history
    history = approval_gateway.get_history()
    assert any(h.approval_id == app_id and h.approved is False for h in history)
