# Phase 18: Automated Bookkeeping
from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="books.record_expense", description="Record a business expense.", parameters={"type":"object","properties":{"amount_jod":{"type":"number"},"category":{"type":"string"},"description":{"type":"string","default":""},"business_id":{"type":"integer","default":0}},"required":["amount_jod","category"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="bookkeeping")
async def record_expense(amount_jod: float, category: str, description: str = "", business_id: int = 0) -> Dict[str, Any]:
    business_db.audit("expense", "bookkeeping", target=category, details={"amount":amount_jod,"desc":description,"bid":business_id})
    return {"ok": True, "recorded": amount_jod, "category": category}

@tool(name="books.record_income", description="Record business income.", parameters={"type":"object","properties":{"amount_jod":{"type":"number"},"source":{"type":"string"},"description":{"type":"string","default":""}},"required":["amount_jod","source"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="bookkeeping")
async def record_income(amount_jod: float, source: str, description: str = "") -> Dict[str, Any]:
    business_db.audit("income", "bookkeeping", target=source, details={"amount":amount_jod,"desc":description})
    return {"ok": True, "recorded": amount_jod, "source": source}

@tool(name="books.pnl", description="Generate monthly P&L (profit & loss) statement.", parameters={"type":"object","properties":{"month":{"type":"string","default":""}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="bookkeeping")
async def pnl(month: str = "") -> Dict[str, Any]:
    inv = business_db.query_one("SELECT COALESCE(SUM(amount),0) as v FROM invoices WHERE status='paid'")["v"]
    orders = business_db.query_one("SELECT COALESCE(SUM(total),0) as v FROM orders WHERE status IN ('paid','delivered')")["v"]
    return {"ok": True, "total_revenue_jod": round(inv+orders,2), "note": "Full P&L with expense tracking coming when expenses are recorded regularly."}

@tool(name="books.tax_estimate", description="Estimate Jordanian income tax based on revenue.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="bookkeeping")
async def tax_estimate() -> Dict[str, Any]:
    from plugins.legal_jo.plugin import jo_tax_calc_income_tax
    inv = business_db.query_one("SELECT COALESCE(SUM(amount),0) as v FROM invoices WHERE status='paid'")["v"]
    return await jo_tax_calc_income_tax(annual_income_jod=inv or 0)

PLUGIN_NAME = "bookkeeping"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Bookkeeping: record expenses/income, P&L, tax estimates."
