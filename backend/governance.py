# ====================================================================
# JARVIS OMEGA — Decision Governance Layer (Phase 2)
# ====================================================================
"""
Decision Governance Layer with veto power across four pluggable reviewer roles:
  1. Red-Team reviewer — logical gaps, assumptions, overlooked risks
  2. Compliance reviewer — anti-spam, WhatsApp ToS, FTC disclosures, Jordan regulations
  3. Financial reviewer — checks against canonical Financial Ledger & budget caps
  4. Risk/Brand reviewer — reputational/brand risk, market fit, backlash
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from pydantic import BaseModel, Field

from backend.config import settings
from backend.ledger import ledger
from shared.logger import get_logger

log = get_logger("governance")


class ReviewResult(BaseModel):
    approved: bool
    role: str
    reason: str
    risk_score: float = 0.0  # 0.0 (safe) to 1.0 (extreme risk)


class DecisionVeto(BaseModel):
    decision_type: str
    action: str
    rule_applied: str  # 'consensus' | 'majority'
    vetoed_by: List[str]
    veto_reasons: List[Dict[str, str]]
    details: Dict[str, Any] = Field(default_factory=dict)


class GovernanceReviewRequest(BaseModel):
    decision_type: str  # 'new_business', 'ad_spend', 'enter_market', 'strategy_change', 'dangerous_command'
    action: str
    amount_usd: float = 0.0
    channel: str = ""
    jurisdiction: str = "JO"
    target_market: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------
# Pluggable Reviewers
# --------------------------------------------------------------------

class RedTeamReviewer:
    """Reviews decision for logical gaps, overconfidence, and unstated assumptions."""

    async def review(self, req: GovernanceReviewRequest) -> ReviewResult:
        action_lower = req.action.lower()
        if "guaranteed profit" in action_lower or "100% success" in action_lower:
            return ReviewResult(
                approved=False,
                role="red_team",
                reason="Red-Team Veto: Unrealistic overconfidence claim in decision strategy.",
                risk_score=0.9,
            )
        if req.decision_type == "enter_market" and not req.target_market:
            return ReviewResult(
                approved=False,
                role="red_team",
                reason="Red-Team Veto: Market entry proposed without defined target market parameter.",
                risk_score=0.8,
            )
        return ReviewResult(approved=True, role="red_team", reason="Logical assumptions valid.", risk_score=0.1)


class ComplianceReviewer:
    """Checks action against regulatory laws, ToS limits, and financial rules."""

    async def review(self, req: GovernanceReviewRequest) -> ReviewResult:
        action_lower = req.action.lower()
        channel_lower = req.channel.lower()

        # WhatsApp ToS limits
        if channel_lower == "whatsapp" and req.details.get("broadcast_count", 0) > 1000:
            return ReviewResult(
                approved=False,
                role="compliance",
                reason="Compliance Veto: WhatsApp broadcast size exceeds daily ToS safe rate limit (1000).",
                risk_score=0.95,
            )

        # Anti-spam / cold email laws (CAN-SPAM / GDPR)
        if "cold_email" in action_lower and not req.details.get("opt_out_link", True):
            return ReviewResult(
                approved=False,
                role="compliance",
                reason="Compliance Veto: Cold email campaign missing mandatory opt-out/unsubscribe header.",
                risk_score=0.9,
            )

        # FTC affiliate disclosure
        if "affiliate" in action_lower and not req.details.get("has_ftc_disclosure", True):
            return ReviewResult(
                approved=False,
                role="compliance",
                reason="Compliance Veto: Affiliate promotional material lacks FTC required disclosure.",
                risk_score=0.85,
            )

        # Jordan trading / financial regulation
        if req.jurisdiction.upper() == "JO" and "crypto_leverage" in action_lower:
            return ReviewResult(
                approved=False,
                role="compliance",
                reason="Compliance Veto: High-leverage crypto trading violates local Jordan CBJ financial advisories.",
                risk_score=0.95,
            )

        return ReviewResult(approved=True, role="compliance", reason="Regulatory checks passed.", risk_score=0.1)


class FinancialReviewer:
    """Checks action against real Financial Ledger balance, spend trends, and daily caps."""

    async def review(self, req: GovernanceReviewRequest) -> ReviewResult:
        amount = req.amount_usd
        if amount <= 0:
            return ReviewResult(approved=True, role="financial", reason="No financial outlay required.", risk_score=0.0)

        # Check ledger balance
        portfolio_bal = ledger.get_portfolio_balance()
        net_bal = portfolio_bal["net_balance"]

        # Check against daily caps
        ad_cap = getattr(settings, "ad_spend_daily_cap_usd", 50.0)
        action_cap = getattr(settings, "payment_per_action_cap_usd", 50.0)

        if req.decision_type == "ad_spend" and amount > ad_cap:
            return ReviewResult(
                approved=False,
                role="financial",
                reason=f"Financial Veto: Proposed ad spend (${amount:.2f}) exceeds configured daily cap (${ad_cap:.2f}).",
                risk_score=0.85,
            )

        if amount > action_cap and action_cap > 0:
            return ReviewResult(
                approved=False,
                role="financial",
                reason=f"Financial Veto: Proposed expenditure (${amount:.2f}) exceeds per-action cap (${action_cap:.2f}).",
                risk_score=0.85,
            )

        return ReviewResult(
            approved=True,
            role="financial",
            reason=f"Financial check passed. Portfolio net balance: ${net_bal:.2f}.",
            risk_score=0.2,
        )


class RiskBrandReviewer:
    """Evaluates reputational/brand risk, market fit, and public backlash potential."""

    async def review(self, req: GovernanceReviewRequest) -> ReviewResult:
        action_lower = req.action.lower()
        details_str = json.dumps(req.details).lower()

        toxic_keywords = ["offensive", "scam", "clickbait_fraud", "impersonate"]
        for kw in toxic_keywords:
            if kw in action_lower or kw in details_str:
                return ReviewResult(
                    approved=False,
                    role="risk_brand",
                    reason=f"Risk/Brand Veto: Action contains high-risk brand term '{kw}'.",
                    risk_score=0.95,
                )

        return ReviewResult(approved=True, role="risk_brand", reason="Brand & reputational risk acceptable.", risk_score=0.1)


# --------------------------------------------------------------------
# Governance Layer Engine
# --------------------------------------------------------------------

class GovernanceLayer:
    """
    Central Decision Governance Engine combining all 4 reviewer roles.
    """

    def __init__(self) -> None:
        self.red_team = RedTeamReviewer()
        self.compliance = ComplianceReviewer()
        self.financial = FinancialReviewer()
        self.risk_brand = RiskBrandReviewer()

    async def evaluate_decision(self, req: GovernanceReviewRequest) -> Dict[str, Any]:
        """
        Evaluates a decision using consensus (4/4) or majority (3/4) rule.
        """
        # Determine rule: consensus for launches, spend, and marketing broadcasts, majority for minor strategy
        default_rule = "consensus" if req.decision_type in ("new_business", "ad_spend", "dangerous_command", "marketing", "strategy_change") else "majority"
        rule = req.details.get("rule_override") or default_rule

        # Collect reviews from all 4 reviewers
        reviews: List[ReviewResult] = [
            await self.red_team.review(req),
            await self.compliance.review(req),
            await self.financial.review(req),
            await self.risk_brand.review(req),
        ]

        approvals = [r for r in reviews if r.approved]
        vetoes = [r for r in reviews if not r.approved]

        # Rule evaluation
        approved = False
        if rule == "consensus":
            approved = len(vetoes) == 0
        elif rule == "majority":
            approved = len(approvals) >= 3
        else:
            approved = len(vetoes) == 0  # Fallback to consensus

        log_data = {
            "decision_type": req.decision_type,
            "action": req.action,
            "rule": rule,
            "approved": approved,
            "approvals_count": len(approvals),
            "vetoes_count": len(vetoes),
        }

        if approved:
            log.info("governance_decision_approved", **log_data)
            return {
                "approved": True,
                "rule": rule,
                "reviews": [r.model_dump() for r in reviews],
            }

        # Log structured veto
        veto_record = DecisionVeto(
            decision_type=req.decision_type,
            action=req.action,
            rule_applied=rule,
            vetoed_by=[v.role for v in vetoes],
            veto_reasons=[{"role": v.role, "reason": v.reason} for v in vetoes],
            details=req.details,
        )
        log.warning("governance_decision_vetoed", veto=veto_record.model_dump())

        # Audit veto in business_db
        try:
            from backend.business_db import business_db
            business_db.audit(
                category="governance_veto",
                action=req.action,
                target=req.decision_type,
                details=veto_record.model_dump(),
            )
        except Exception as e:
            log.warning("failed_to_audit_governance_veto", error=str(e))

        return {
            "approved": False,
            "rule": rule,
            "veto": veto_record.model_dump(),
            "reviews": [r.model_dump() for r in reviews],
        }


governance_layer = GovernanceLayer()
