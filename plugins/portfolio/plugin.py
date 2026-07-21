# ====================================================================
# JARVIS OMEGA - Portfolio Plugin (Phase 12)
# ====================================================================
"""
Manage up to 50 businesses at once. Each business has its own:
  - niche + product(s) + landing page + deploy URL
  - revenue / leads / orders KPIs
  - status (idea → building → live → paused → archived)

Tools:
  portfolio.add_business / list / update / archive
  portfolio.kpis                - per-business KPIs (revenue, leads, posts, orders)
  portfolio.dashboard           - aggregate view of the whole portfolio
  portfolio.cap_available       - how many of the 50 slots are free
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("portfolio")


@tool(
    name="portfolio.add_business",
    description="Add a new business to the portfolio. Caps at PORTFOLIO_MAX_BUSINESSES.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "niche": {"type": "string"},
            "language": {"type": "string", "default": "ar"},
            "country": {"type": "string", "default": "JO"},
            "currency": {"type": "string", "default": "JOD"},
            "city": {"type": "string", "default": "Amman"},
            "monetization": {"type": "string", "default": "service"},
            "target_revenue_monthly": {"type": "number", "default": 0},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["name", "niche"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="portfolio",
)
async def portfolio_add_business(
    name: str, niche: str, language: str = "ar", country: str = "JO",
    currency: str = "JOD", city: str = "Amman",
    monetization: str = "service", target_revenue_monthly: float = 0,
    notes: str = "",
) -> Dict[str, Any]:
    # Enforce the 50-business cap.
    current = len(business_db.query("SELECT id FROM businesses"))
    if current >= settings.portfolio_max_businesses:
        return {
            "ok": False,
            "error": f"portfolio cap reached ({settings.portfolio_max_businesses}). Archive an old business first.",
        }
    bid = business_db.execute(
        """INSERT INTO businesses (name, niche, language, country, currency, city,
                                   monetization, target_revenue_monthly, notes,
                                   status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'idea', ?, ?)""",
        (name, niche, language, country, currency, city,
         monetization, target_revenue_monthly, notes,
         datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )
    business_db.audit("add_business", "portfolio", target=name, details={"business_id": bid})
    return {
        "ok": True, "business_id": bid, "name": name, "niche": niche,
        "slots_remaining": settings.portfolio_max_businesses - current - 1,
    }


@tool(
    name="portfolio.list_businesses",
    description="List all businesses in the portfolio. Filter by status.",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 100},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="portfolio",
)
async def portfolio_list_businesses(status: str = "", limit: int = 100) -> Dict[str, Any]:
    sql = "SELECT * FROM businesses"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {
        "ok": True,
        "count": len(rows),
        "max_capacity": settings.portfolio_max_businesses,
        "businesses": rows,
    }


@tool(
    name="portfolio.update_business",
    description="Update a business (status, deployed URL, revenue, notes).",
    parameters={
        "type": "object",
        "properties": {
            "business_id": {"type": "integer"},
            "status": {"type": "string", "default": "", "enum": ["", "idea", "building", "live", "paused", "archived"]},
            "deployed_url": {"type": "string", "default": ""},
            "landing_path": {"type": "string", "default": ""},
            "actual_revenue_monthly": {"type": "number", "default": -1},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["business_id"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="portfolio",
)
async def portfolio_update_business(
    business_id: int, status: str = "", deployed_url: str = "",
    landing_path: str = "", actual_revenue_monthly: float = -1,
    notes: str = "",
) -> Dict[str, Any]:
    sets: List[str] = ["updated_at = ?"]
    params: List[Any] = [datetime.utcnow().isoformat()]
    if status:
        sets.append("status = ?")
        params.append(status)
    if deployed_url:
        sets.append("deployed_url = ?")
        params.append(deployed_url)
    if landing_path:
        sets.append("landing_path = ?")
        params.append(landing_path)
    if actual_revenue_monthly >= 0:
        sets.append("actual_revenue_monthly = ?")
        params.append(actual_revenue_monthly)
    if notes:
        sets.append("notes = ?")
        params.append(notes)
    params.append(business_id)
    business_db.execute(f"UPDATE businesses SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return {"ok": True, "business_id": business_id}


@tool(
    name="portfolio.kpis",
    description="Get per-business KPIs: revenue (paid invoices), orders, posts, leads.",
    parameters={
        "type": "object",
        "properties": {
            "business_id": {"type": "integer"},
            "days": {"type": "integer", "default": 30},
        },
        "required": ["business_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="portfolio",
)
async def portfolio_kpis(business_id: int, days: int = 30) -> Dict[str, Any]:
    biz = business_db.query_one("SELECT * FROM businesses WHERE id = ?", (business_id,))
    if not biz:
        return {"ok": False, "error": f"business not found: {business_id}"}
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    # Treat the business's name as the "client name" proxy for invoice/order rollup.
    biz_name = biz["name"]

    # Link to clients table where clients.name = businesses.name.
    client = business_db.query_one("SELECT id FROM clients WHERE name = ?", (biz_name,))
    client_id = client["id"] if client else None

    revenue = 0
    invoice_count = 0
    order_count = 0
    post_count = 0
    leads = 0

    if client_id:
        inv = business_db.query_one(
            "SELECT COUNT(*) as n, COALESCE(SUM(amount), 0) as v FROM invoices "
            "WHERE client_id = ? AND status = 'paid' AND paid_at >= ?",
            (client_id, since),
        )
        if inv:
            invoice_count = inv["n"]
            revenue = inv["v"]
        orders = business_db.query_one(
            "SELECT COUNT(*) as n FROM orders WHERE client_id = ? AND created_at >= ?",
            (client_id, since),
        )
        if orders:
            order_count = orders["n"]
        # Posts via campaign → client
        posts = business_db.query_one(
            "SELECT COUNT(*) as n FROM posts p JOIN campaigns c ON p.campaign_id = c.id "
            "WHERE c.client_id = ? AND p.created_at >= ?",
            (client_id, since),
        )
        if posts:
            post_count = posts["n"]
        leads_count = business_db.query_one(
            "SELECT COUNT(*) as n FROM deals WHERE client_id = ? AND created_at >= ?",
            (client_id, since),
        )
        if leads_count:
            leads = leads_count["n"]

    target = biz["target_revenue_monthly"] or 0
    return {
        "ok": True,
        "business_id": business_id,
        "name": biz_name,
        "niche": biz["niche"],
        "status": biz["status"],
        "deployed_url": biz["deployed_url"],
        "days_window": days,
        "kpis": {
            "revenue": revenue,
            "currency": biz["currency"],
            "paid_invoices": invoice_count,
            "orders": order_count,
            "posts": post_count,
            "leads": leads,
            "target_revenue_monthly": target,
            "target_attainment_pct": round((revenue / target * 100), 1) if target else 0.0,
        },
    }


@tool(
    name="portfolio.dashboard",
    description="Aggregate view of the whole portfolio: business count, total revenue, active vs paused, top performers.",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 30},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="portfolio",
)
async def portfolio_dashboard(days: int = 30) -> Dict[str, Any]:
    total = business_db.query_one("SELECT COUNT(*) as n FROM businesses")["n"]
    by_status = business_db.rows_to_dicts(business_db.query(
        "SELECT status, COUNT(*) as n FROM businesses GROUP BY status"
    ))
    by_currency = business_db.rows_to_dicts(business_db.query(
        "SELECT currency, COUNT(*) as n FROM businesses GROUP BY currency"
    ))

    # Per-business revenue in the window.
    businesses = business_db.rows_to_dicts(business_db.query("SELECT id, name FROM businesses"))
    performers: List[Dict[str, Any]] = []
    for b in businesses:
        kpi = await portfolio_kpis(b["id"], days=days)
        if kpi.get("ok"):
            performers.append({
                "id": b["id"], "name": b["name"],
                "revenue": kpi["kpis"]["revenue"],
                "currency": kpi["kpis"]["currency"],
                "orders": kpi["kpis"]["orders"],
                "posts": kpi["kpis"]["posts"],
            })
    performers.sort(key=lambda p: p["revenue"], reverse=True)

    return {
        "ok": True,
        "window_days": days,
        "total_businesses": total,
        "capacity": settings.portfolio_max_businesses,
        "slots_used_pct": round(total / settings.portfolio_max_businesses * 100, 1),
        "by_status": {r["status"]: r["n"] for r in by_status},
        "by_currency": {r["currency"]: r["n"] for r in by_currency},
        "top_performers": performers[:10],
    }


@tool(
    name="portfolio.cap_available",
    description="How many of the 50 portfolio slots are still free.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="portfolio",
)
async def portfolio_cap_available() -> Dict[str, Any]:
    used = business_db.query_one("SELECT COUNT(*) as n FROM businesses")["n"]
    cap = settings.portfolio_max_businesses
    return {
        "ok": True,
        "used": used,
        "remaining": max(0, cap - used),
        "capacity": cap,
    }


PLUGIN_NAME = "portfolio"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Manage up to 50 businesses with per-business KPIs and a portfolio dashboard."
