# JARVIS OMEGA - Delivery Optimization Amman (Phase 16)
from __future__ import annotations
import json, math
from datetime import datetime
from typing import Any, Dict, List
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="delivery.optimize_route", description="Optimize a multi-stop delivery route in Amman. Returns ordered stops + estimated time.", parameters={"type":"object","properties":{"stops":{"type":"array","items":{"type":"object"},"description":"[{name, lat, lon, address}]"},"driver_name":{"type":"string","default":"Driver 1"}},"required":["stops"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="delivery_jo")
async def optimize_route(stops: List[Dict], driver_name: str = "Driver 1") -> Dict[str, Any]:
    if len(stops) < 2: return {"ok": False, "error": "need at least 2 stops"}
    # Nearest-neighbor heuristic
    remaining = list(enumerate(stops))
    route = [remaining.pop(0)]
    while remaining:
        last = route[-1][1]
        best = min(remaining, key=lambda x: _dist(last, x[1]))
        route.append(best)
        remaining.remove(best)
    ordered = [{"order": i+1, "name": s["name"], "address": s.get("address",""), "lat": s.get("lat"), "lon": s.get("lon")} for i, (_, s) in enumerate(route)]
    total_dist = sum(_dist(route[i][1], route[i+1][1]) for i in range(len(route)-1))
    est_minutes = int(total_dist * 3)  # rough: 3 min per km in Amman traffic
    rid = business_db.execute("INSERT INTO delivery_routes (driver_name, date, stops_json, status, optimized, created_at) VALUES (?, ?, ?, 'planned', 1, ?)",
        (driver_name, datetime.utcnow().date().isoformat(), json.dumps(ordered), datetime.utcnow().isoformat()))
    return {"ok": True, "route_id": rid, "ordered_stops": ordered, "estimated_km": round(total_dist, 1), "estimated_minutes": est_minutes}

def _dist(a: Dict, b: Dict) -> float:
    try: return math.sqrt((float(a.get("lat",0))-float(b.get("lat",0)))**2 + (float(a.get("lon",0))-float(b.get("lon",0)))**2) * 111
    except: return 999

@tool(name="delivery.tracking_link", description="Generate a customer-facing Arabic tracking message with estimated arrival.", parameters={"type":"object","properties":{"customer_name":{"type":"string"},"eta_minutes":{"type":"integer","default":30},"order_id":{"type":"string","default":""}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="delivery_jo")
async def tracking_link(customer_name: str = "", eta_minutes: int = 30, order_id: str = "") -> Dict[str, Any]:
    msg = f"🚚 {customer_name or 'عميلنا العزيز'}، طلبك{f' رقم {order_id}' if order_id else ''} في الطريق!\n⏱️ سيصلك خلال ~{eta_minutes} دقيقة.\nشكراً لصبرك 🌟"
    return {"ok": True, "tracking_message": msg}

@tool(name="delivery.list_routes", description="List all delivery routes.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="delivery_jo")
async def list_routes() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT * FROM delivery_routes ORDER BY id DESC LIMIT 20"))
    return {"ok": True, "routes": rows}

PLUGIN_NAME = "delivery_jo"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Amman delivery: route optimization + customer tracking."
