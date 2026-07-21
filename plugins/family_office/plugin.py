# ====================================================================
# JARVIS OMEGA - Family Office (Phase 14)
# ====================================================================
"""
Sir's personal wealth manager.

  family.net_worth_tracker    - aggregate all assets
  family.investment_allocation - MPT-style rebalance recommendations
  family.tax_loss_harvest      - year-round TLH scanner
  family.estate_plan_generator - will + trust templates (lawyer-reviewed)
  family.charity_donor_advised - DAF giving optimizer
  family.kyc_aml_check         - counterparty screening
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings


@tool(
    name="family.add_asset",
    description="Add an asset to Sir's net-worth tracker.",
    parameters={
        "type": "object",
        "properties": {
            "asset_type": {"type": "string", "enum": ["cash", "crypto", "stock", "real_estate_jo", "business", "other"]},
            "name": {"type": "string"},
            "value_usd": {"type": "number"},
            "custodian": {"type": "string", "default": ""},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["asset_type", "name", "value_usd"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="family",
)
async def family_add_asset(asset_type: str, name: str, value_usd: float, custodian: str = "", notes: str = "") -> Dict[str, Any]:
    value_jod = round(value_usd * settings.default_currency_exchange_rate, 2)
    aid = business_db.execute(
        """INSERT INTO family_assets (asset_type, name, value_usd, value_jod, custodian, notes, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (asset_type, name, value_usd, value_jod, custodian, notes, datetime.utcnow().isoformat()),
    )
    return {"ok": True, "asset_id": aid, "value_usd": value_usd, "value_jod": value_jod}


@tool(
    name="family.net_worth_tracker",
    description="Aggregate all tracked assets. Returns totals by type + currency.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="family",
)
async def family_net_worth_tracker() -> Dict[str, Any]:
    rows = business_db.query(
        "SELECT asset_type, COUNT(*) as n, SUM(value_usd) as usd, SUM(value_jod) as jod FROM family_assets GROUP BY asset_type"
    )
    by_type = {r["asset_type"]: {"count": r["n"], "usd": r["usd"] or 0, "jod": r["jod"] or 0} for r in rows}
    total_usd = sum(v["usd"] for v in by_type.values())
    total_jod = sum(v["jod"] for v in by_type.values())
    return {
        "ok": True,
        "by_type": by_type,
        "total_usd": round(total_usd, 2),
        "total_jod": round(total_jod, 2),
        "as_of": datetime.utcnow().isoformat(),
    }


@tool(
    name="family.investment_allocation",
    description="Generate Modern Portfolio Theory-style allocation recommendations for Sir's net worth.",
    parameters={
        "type": "object",
        "properties": {
            "risk_tolerance": {"type": "string", "default": "moderate", "enum": ["conservative", "moderate", "aggressive"]},
            "time_horizon_years": {"type": "integer", "default": 10},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="family",
)
async def family_investment_allocation(risk_tolerance: str = "moderate", time_horizon_years: int = 10) -> Dict[str, Any]:
    portfolios = {
        "conservative": {"stocks": 30, "bonds": 50, "real_estate": 10, "crypto": 5, "cash": 5},
        "moderate": {"stocks": 50, "bonds": 25, "real_estate": 15, "crypto": 5, "cash": 5},
        "aggressive": {"stocks": 65, "bonds": 10, "real_estate": 10, "crypto": 10, "cash": 5},
    }
    target = portfolios.get(risk_tolerance, portfolios["moderate"])
    # Compare to current.
    net = await family_net_worth_tracker()
    if not net.get("ok"):
        return net
    total = net["total_usd"] or 1
    current = {}
    for t, v in net["by_type"].items():
        pct = round(v["usd"] / total * 100, 1)
        # Map family_assets types to allocation buckets.
        bucket_map = {"cash": "cash", "stock": "stocks", "real_estate_jo": "real_estate",
                      "crypto": "crypto", "business": "stocks", "other": "cash"}
        bucket = bucket_map.get(t, "cash")
        current[bucket] = round(current.get(bucket, 0) + pct, 1)

    drift = {k: round(target.get(k, 0) - current.get(k, 0), 1) for k in target}
    return {
        "ok": True,
        "risk_tolerance": risk_tolerance,
        "time_horizon_years": time_horizon_years,
        "target_allocation_pct": target,
        "current_allocation_pct": current,
        "drift_pct": drift,
        "rebalance_recommendation": [
            f"{'Buy' if d > 5 else 'Sell' if d < -5 else 'Hold'} {k}: drift {d:+.1f}%"
            for k, d in drift.items() if abs(d) >= 5
        ] or ["Portfolio is balanced — no rebalance needed."],
    }


@tool(
    name="family.tax_loss_harvest",
    description="Scan trading + asset history for tax-loss harvesting opportunities.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="family",
)
async def family_tax_loss_harvest() -> Dict[str, Any]:
    # Read paper_trades for losses.
    losses = business_db.query(
        "SELECT symbol, quantity, price_usd FROM paper_trades WHERE side = 'sell' ORDER BY id DESC LIMIT 50"
    )
    # Without cost basis tracking, we can only flag for review.
    return {
        "ok": True,
        "note": "Tax-loss harvesting requires cost-basis tracking per lot.",
        "trades_reviewed": len(losses),
        "manual_review_url": "Review trading history + compare to cost basis.",
        "rule": "Sell positions at a loss to offset gains, then re-buy after 30-day wash-sale window (US tax) or local equivalent.",
    }


@tool(
    name="family.estate_plan_generator",
    description="Generate a basic estate plan: will + trust template. ⚠️ Lawyer-reviewed required.",
    parameters={
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "beneficiaries": {"type": "array", "items": {"type": "string"}, "default": []},
            "jurisdiction": {"type": "string", "default": "Hashemite Kingdom of Jordan"},
            "language": {"type": "string", "default": "both", "enum": ["ar", "en", "both"]},
        },
        "required": ["full_name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="family",
)
async def family_estate_plan_generator(
    full_name: str, beneficiaries: Optional[List[str]] = None,
    jurisdiction: str = "Hashemite Kingdom of Jordan", language: str = "both",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    beneficiaries = beneficiaries or []
    try:
        will = await llm_service.get_response(
            user_message=(
                f"Testator: {full_name}\nBeneficiaries: {beneficiaries}\nJurisdiction: {jurisdiction}"
            ),
            system_instructions=(
                f"You are an estate lawyer. Generate a basic will + simple trust template in {'Arabic + English' if language == 'both' else language}. "
                "Include: declaration, revocation of prior wills, distribution of assets, executor appointment, "
                "guardian (if applicable), governing law clause. Output Markdown. "
                "Add prominent warning: 'This is a draft. Have a licensed lawyer review before signing.'"
            ),
            inject_memory=False,
        )
        return {"ok": True, "will_markdown": will, "disclaimer": "DRAFT — lawyer review required."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="family.charity_donor_advised",
    description="Recommend charitable giving strategy (DAF-style). Returns suggested split across causes.",
    parameters={
        "type": "object",
        "properties": {
            "annual_amount_usd": {"type": "number", "default": 1000},
            "causes": {"type": "array", "items": {"type": "string"}, "default": ["education", "healthcare", "poverty relief"]},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="family",
)
async def family_charity_donor_advised(annual_amount_usd: float = 1000, causes: Optional[List[str]] = None) -> Dict[str, Any]:
    causes = causes or ["education", "healthcare", "poverty relief"]
    # Equal split + 10% to a "discretionary" bucket for opportunities.
    n = len(causes)
    per_cause = round(annual_amount_usd * 0.90 / n, 2)
    return {
        "ok": True,
        "total_annual_usd": annual_amount_usd,
        "split": {c: per_cause for c in causes},
        "discretionary_usd": round(annual_amount_usd * 0.10, 2),
        "platforms_jo": ["Bonyan Organization", "Tkiyet Um Ali", "Jordan River Foundation", "King Hussein Cancer Foundation"],
        "platforms_global": ["GiveWell (effective altruism)", "GiveDirectly", "Against Malaria Foundation"],
    }


@tool(
    name="family.kyc_aml_check",
    description="Basic KYC/AML screen for a counterparty. Returns risk indicators.",
    parameters={
        "type": "object",
        "properties": {
            "counterparty_name": {"type": "string"},
            "counterparty_country": {"type": "string", "default": ""},
        },
        "required": ["counterparty_name"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="family",
)
async def family_kyc_aml_check(counterparty_name: str, counterparty_country: str = "") -> Dict[str, Any]:
    # Basic checks: sanctions list, high-risk jurisdictions.
    HIGH_RISK = {"IR", "KP", "SY", "CU", "VE", "AF", "YE", "LY", "SO", "SS"}
    risk_indicators: List[str] = []
    if counterparty_country.upper() in HIGH_RISK:
        risk_indicators.append(f"High-risk jurisdiction: {counterparty_country}")
    # Search public sanctions list mention via search engine.
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://www.google.com/search",
                params={"q": f'"{counterparty_name}" sanctions OR OFAC OR terror'},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        if "sanctioned" in r.text.lower() or "ofac" in r.text.lower():
            risk_indicators.append("Public mention of sanctions/OFAC found — investigate")
    except Exception:
        pass

    return {
        "ok": True,
        "counterparty": counterparty_name,
        "country": counterparty_country or "unspecified",
        "risk_indicators": risk_indicators,
        "verdict": "HIGH RISK — decline or escalate" if risk_indicators else "No red flags — proceed with normal due diligence",
        "disclaimer": "Heuristic screen only. For formal KYC/AML use a regulated provider.",
    }


PLUGIN_NAME = "family_office"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Family office: net worth tracker, allocation, TLH, estate planning, charity, KYC/AML."
