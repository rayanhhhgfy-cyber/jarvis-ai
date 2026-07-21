# Phase 18: Business Intelligence Dashboard
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="bi.dashboard", description="Full dashboard: all businesses, revenue, pipeline, content, alerts.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business_intelligence")
async def dashboard() -> Dict[str, Any]:
    businesses = business_db.query_one("SELECT COUNT(*) as n FROM businesses")["n"]
    live = business_db.query_one("SELECT COUNT(*) as n FROM businesses WHERE status='live'")["n"]
    revenue = business_db.query_one("SELECT COALESCE(SUM(amount),0) as v FROM invoices WHERE status='paid'")["v"]
    orders = business_db.query_one("SELECT COUNT(*) as n FROM orders")["n"]
    deals = business_db.query_one("SELECT COUNT(*) as n FROM sales_conversations WHERE status='deal_closed'")["n"]
    posts = business_db.query_one("SELECT COUNT(*) as n FROM posts")["n"]
    return {"ok": True, "metrics": {"businesses_total": businesses, "businesses_live": live, "revenue_jod": round(revenue,2), "orders": orders, "deals_closed": deals, "posts_published": posts}}

@tool(name="bi.per_business", description="Per-business breakdown: revenue, orders, posts, deals.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="business_intelligence")
async def per_business() -> Dict[str, Any]:
    from plugins.portfolio.plugin import portfolio_dashboard
    return await portfolio_dashboard(days=30)

PLUGIN_NAME = "business_intelligence"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Business intelligence: full dashboard + per-business breakdown."
