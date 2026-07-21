# JARVIS OMEGA - Subscription Box (Phase 16)
from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="subbox.create", description="Create a subscription box offering.", parameters={"type":"object","properties":{"name":{"type":"string"},"niche":{"type":"string"},"monthly_price_jod":{"type":"number","default":30},"items":{"type":"array","items":{"type":"string"},"default":[]}},"required":["name","niche"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="subscription_box")
async def subbox_create(name: str, niche: str, monthly_price_jod: float = 30, items: Optional[List[str]] = None) -> Dict[str, Any]:
    items = items or []
    bid = business_db.execute("INSERT INTO subscription_boxes (name, niche, monthly_price_jod, items_json, status, created_at) VALUES (?,?,?,?,?,?)",
        (name, niche, monthly_price_jod, json.dumps(items), "active", datetime.utcnow().isoformat()))
    return {"ok": True, "box_id": bid, "name": name, "price": monthly_price_jod}

@tool(name="subbox.subscribe", description="Add a subscriber to a box.", parameters={"type":"object","properties":{"box_id":{"type":"integer"},"customer_name":{"type":"string"},"customer_phone":{"type":"string"},"customer_address":{"type":"string","default":""}},"required":["box_id","customer_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="subscription_box")
async def subbox_subscribe(box_id: int, customer_name: str, customer_phone: str = "", customer_address: str = "") -> Dict[str, Any]:
    sid = business_db.execute("INSERT INTO subscription_subscribers (box_id, customer_name, customer_phone, customer_address, status, started_at) VALUES (?,?,?,?,?,?)",
        (box_id, customer_name, customer_phone, customer_address, "active", datetime.utcnow().isoformat()))
    business_db.execute("UPDATE subscription_boxes SET subscriber_count = subscriber_count + 1 WHERE id = ?", (box_id,))
    return {"ok": True, "subscription_id": sid}

@tool(name="subbox.list", description="List all subscription boxes.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="subscription_box")
async def subbox_list() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT * FROM subscription_boxes ORDER BY id DESC"))
    return {"ok": True, "boxes": rows}

@tool(name="subbox.mrr", description="Calculate Monthly Recurring Revenue from subscriptions.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="subscription_box")
async def subbox_mrr() -> Dict[str, Any]:
    rows = business_db.query("SELECT b.monthly_price_jod, COUNT(s.id) as subs FROM subscription_boxes b LEFT JOIN subscription_subscribers s ON b.id = s.box_id AND s.status = 'active' GROUP BY b.id")
    total = sum(r["monthly_price_jod"] * r["subs"] for r in rows)
    return {"ok": True, "mrr_jod": round(total, 2), "by_box": [dict(r) for r in rows]}

PLUGIN_NAME = "subscription_box"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Subscription box: create, subscribe, track MRR."
