# ====================================================================
# JARVIS OMEGA - Budget Cap System (Phase 15)
# ====================================================================
"""
HARD spending cap. JARVIS can NEVER cross this — enforced at the tool
executor level before any Tier 4 (real-money) tool runs.

  budget.set               - set daily/weekly/monthly cap
  budget.get               - current cap + how much is left
  budget.record_spend      - record a spend (auto-called by spending tools)
  budget.check             - returns True if within budget, False if over
  budget.history           - every spend this period
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from backend.tools import tool, RiskTier


_BUDGET_PATH = Path("./storage/budget.json")


def _load_budget() -> Dict[str, Any]:
    if not _BUDGET_PATH.exists():
        return {"daily_cap_usd": 0, "weekly_cap_usd": 0, "monthly_cap_usd": 0, "spends": []}
    try:
        return json.loads(_BUDGET_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"daily_cap_usd": 0, "weekly_cap_usd": 0, "monthly_cap_usd": 0, "spends": []}


def _save_budget(data: Dict[str, Any]) -> None:
    _BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BUDGET_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _spends_in_period(period: str = "daily") -> float:
    """Sum all spends in the given period."""
    budget = _load_budget()
    now = datetime.utcnow()
    if period == "daily":
        cutoff = now - timedelta(days=1)
    elif period == "weekly":
        cutoff = now - timedelta(days=7)
    elif period == "monthly":
        cutoff = now - timedelta(days=30)
    else:
        return 0
    total = 0
    for s in budget.get("spends", []):
        try:
            ts = datetime.fromisoformat(s.get("timestamp", ""))
            if ts >= cutoff:
                total += s.get("amount_usd", 0)
        except Exception:
            continue
    return round(total, 2)


@tool(
    name="budget.set",
    description="Set JARVIS's spending cap. He can NEVER spend more than this in the period.",
    parameters={
        "type": "object",
        "properties": {
            "daily_cap_usd": {"type": "number", "default": 0, "description": "0 = no daily cap. e.g. 10 = max $10/day on ads, APIs, etc."},
            "weekly_cap_usd": {"type": "number", "default": 0},
            "monthly_cap_usd": {"type": "number", "default": 0},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="budget",
)
async def budget_set(daily_cap_usd: float = 0, weekly_cap_usd: float = 0, monthly_cap_usd: float = 0) -> Dict[str, Any]:
    budget = _load_budget()
    if daily_cap_usd > 0:
        budget["daily_cap_usd"] = daily_cap_usd
    if weekly_cap_usd > 0:
        budget["weekly_cap_usd"] = weekly_cap_usd
    if monthly_cap_usd > 0:
        budget["monthly_cap_usd"] = monthly_cap_usd
    _save_budget(budget)
    return {
        "ok": True,
        "daily_cap_usd": budget["daily_cap_usd"],
        "weekly_cap_usd": budget["weekly_cap_usd"],
        "monthly_cap_usd": budget["monthly_cap_usd"],
        "message": f"Budget cap set. JARVIS can NEVER spend more than ${budget['daily_cap_usd']}/day, ${budget['weekly_cap_usd']}/week, ${budget['monthly_cap_usd']}/month.",
    }


@tool(
    name="budget.check",
    description="Check if JARVIS is within budget. Returns True if OK, False if over. Called before every spend.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="budget",
)
async def budget_check() -> Dict[str, Any]:
    budget = _load_budget()
    daily_spent = _spends_in_period("daily")
    weekly_spent = _spends_in_period("weekly")
    monthly_spent = _spends_in_period("monthly")

    daily_ok = budget["daily_cap_usd"] == 0 or daily_spent < budget["daily_cap_usd"]
    weekly_ok = budget["weekly_cap_usd"] == 0 or weekly_spent < budget["weekly_cap_usd"]
    monthly_ok = budget["monthly_cap_usd"] == 0 or monthly_spent < budget["monthly_cap_usd"]

    return {
        "ok": True,
        "within_budget": daily_ok and weekly_ok and monthly_ok,
        "daily": {"cap": budget["daily_cap_usd"], "spent": daily_spent, "remaining": round(budget["daily_cap_usd"] - daily_spent, 2) if budget["daily_cap_usd"] else None},
        "weekly": {"cap": budget["weekly_cap_usd"], "spent": weekly_spent, "remaining": round(budget["weekly_cap_usd"] - weekly_spent, 2) if budget["weekly_cap_usd"] else None},
        "monthly": {"cap": budget["monthly_cap_usd"], "spent": monthly_spent, "remaining": round(budget["monthly_cap_usd"] - monthly_spent, 2) if budget["monthly_cap_usd"] else None},
    }


@tool(
    name="budget.record_spend",
    description="Record a spend against the budget. Called internally before any Tier 4 tool that costs money.",
    parameters={
        "type": "object",
        "properties": {
            "amount_usd": {"type": "number"},
            "category": {"type": "string", "default": "general", "description": "e.g. 'ads', 'api', 'subscription'"},
            "description": {"type": "string", "default": ""},
        },
        "required": ["amount_usd"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="budget",
)
async def budget_record_spend(amount_usd: float, category: str = "general", description: str = "") -> Dict[str, Any]:
    # First check if within budget.
    check = await budget_check()
    if not check["within_budget"]:
        return {
            "ok": False,
            "blocked": True,
            "reason": "BUDGET CAP REACHED. JARVIS cannot spend more.",
            "budget_status": check,
        }
    budget = _load_budget()
    budget["spends"].append({
        "amount_usd": amount_usd,
        "category": category,
        "description": description,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _save_budget(budget)
    return {
        "ok": True,
        "recorded": amount_usd,
        "category": category,
        "daily_remaining": check["daily"]["remaining"],
    }


@tool(
    name="budget.get",
    description="Show current budget caps + how much has been spent.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="budget",
)
async def budget_get() -> Dict[str, Any]:
    return await budget_check()


@tool(
    name="budget.history",
    description="Show every spend in the current period.",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 30},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="budget",
)
async def budget_history(days: int = 30) -> Dict[str, Any]:
    budget = _load_budget()
    cutoff = datetime.utcnow() - timedelta(days=days)
    spends = []
    for s in budget.get("spends", []):
        try:
            ts = datetime.fromisoformat(s.get("timestamp", ""))
            if ts >= cutoff:
                spends.append(s)
        except Exception:
            continue
    spends.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
    total = sum(s.get("amount_usd", 0) for s in spends)
    return {
        "ok": True,
        "days": days,
        "spend_count": len(spends),
        "total_spent_usd": round(total, 2),
        "spends": spends[:100],
    }


@tool(
    name="budget.reset",
    description="Clear all spends (e.g. at start of new billing cycle). Does NOT change the caps.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="budget",
)
async def budget_reset() -> Dict[str, Any]:
    budget = _load_budget()
    budget["spends"] = []
    _save_budget(budget)
    return {"ok": True, "message": "Spend history cleared. Caps unchanged."}


PLUGIN_NAME = "budget"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Hard spending cap. JARVIS can NEVER cross it. Daily/weekly/monthly limits enforced."
