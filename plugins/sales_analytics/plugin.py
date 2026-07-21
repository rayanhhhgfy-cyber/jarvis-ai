# Phase 18: Sales Analytics (REAL)
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="sales_analytics.report", description="Full sales analytics: revenue trends, top products, conversion rates, by period.", parameters={"type":"object","properties":{"days":{"type":"integer","default":30}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="sales_analytics")
async def report(days: int = 30) -> Dict[str, Any]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    inv = business_db.query_one("SELECT COUNT(*) as n, COALESCE(SUM(amount),0) as v FROM invoices WHERE status='paid' AND paid_at >= ?", (since,))
    orders = business_db.query_one("SELECT COUNT(*) as n, COALESCE(SUM(total),0) as v FROM orders WHERE status IN ('paid','delivered') AND created_at >= ?", (since,))
    deals = business_db.query_one("SELECT COUNT(*) as total, SUM(CASE WHEN status='deal_closed' THEN 1 ELSE 0 END) as closed, SUM(CASE WHEN status='pitched' THEN 1 ELSE 0 END) as pitched FROM sales_conversations WHERE created_at >= ?", (since,))
    conv_rate = round(deals["closed"] / deals["total"] * 100, 1) if deals["total"] else 0
    top_products = business_db.rows_to_dicts(business_db.query("SELECT p.name, COUNT(o.id) as orders, COALESCE(SUM(o.total),0) as revenue FROM products p LEFT JOIN orders o ON p.id = o.product_id AND o.status IN ('paid','delivered') GROUP BY p.id ORDER BY revenue DESC LIMIT 5"))
    return {"ok": True, "period_days": days, "invoice_revenue": round(inv["v"],2), "order_revenue": round(orders["v"],2), "total_revenue": round(inv["v"]+orders["v"],2), "invoice_count": inv["n"], "order_count": orders["n"], "conversion_rate_pct": conv_rate, "deals_pitched": deals["pitched"], "deals_closed": deals["closed"], "top_products": top_products}

@tool(name="sales_analytics.top_products", description="Show top-selling products by revenue.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="sales_analytics")
async def top_products() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT p.name, COUNT(o.id) as orders, COALESCE(SUM(o.total),0) as revenue FROM products p LEFT JOIN orders o ON p.id = o.product_id GROUP BY p.id ORDER BY revenue DESC LIMIT 10"))
    return {"ok": True, "products": rows}
