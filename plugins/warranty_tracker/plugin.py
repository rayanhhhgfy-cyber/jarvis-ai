# Phase 19: Warranty Tracker (REAL)
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

_WARR_PATH = Path("./storage/warranties.json")

def _load(): return json.loads(_WARR_PATH.read_text(encoding="utf-8")) if _WARR_PATH.exists() else []
def _save(d): _WARR_PATH.parent.mkdir(parents=True, exist_ok=True); _WARR_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")

@tool(name="warranty.add", description="Add a product warranty for tracking.", parameters={"type":"object","properties":{"product_name":{"type":"string"},"purchase_date":{"type":"string"},"warranty_months":{"type":"integer","default":12},"receipt_path":{"type":"string","default":""}},"required":["product_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="warranty_tracker")
async def add(product_name: str, purchase_date: str = "", warranty_months: int = 12, receipt_path: str = "") -> Dict[str, Any]:
    data = _load()
    data.append({"product": product_name, "purchase_date": purchase_date or datetime.utcnow().date().isoformat(), "warranty_months": warranty_months, "receipt": receipt_path})
    _save(data)
    return {"ok": True, "product": product_name, "expires": f"{warranty_months} months from purchase"}

@tool(name="warranty.check_expiring", description="Check which warranties expire in the next 30 days.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="warranty_tracker")
async def check_expiring() -> Dict[str, Any]:
    data = _load()
    now = datetime.utcnow().date()
    expiring = []
    for w in data:
        try:
            purchase = datetime.fromisoformat(w["purchase_date"]).date()
            expiry = purchase + timedelta(days=w["warranty_months"] * 30)
            days_left = (expiry - now).days
            if days_left <= 30:
                expiring.append({"product": w["product"], "expires": expiry.isoformat(), "days_left": days_left, "status": "EXPIRED" if days_left < 0 else "EXPIRING"})
        except: pass
    return {"ok": True, "total_tracked": len(data), "expiring_or_expired": len(expiring), "items": expiring}

@tool(name="warranty.list_all", description="List all tracked warranties.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="warranty_tracker")
async def list_all() -> Dict[str, Any]:
    return {"ok": True, "warranties": _load(), "count": len(_load())}

PLUGIN_NAME = "warranty_tracker"; PLUGIN_VERSION = "1.0.0"
