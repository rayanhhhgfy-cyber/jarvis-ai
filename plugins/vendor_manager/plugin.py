# Phase 18: Vendor/Supplier Manager (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="vendor.add", description="Add a supplier/vendor.", parameters={"type":"object","properties":{"name":{"type":"string"},"phone":{"type":"string","default":""},"product_type":{"type":"string","default":""},"lead_time_days":{"type":"integer","default":7}},"required":["name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="vendor_manager")
async def vendor_add(name: str, phone: str = "", product_type: str = "", lead_time_days: int = 7) -> Dict[str, Any]:
    business_db.audit("vendor_added", "vendor_manager", target=name, details={"phone": phone, "product": product_type, "lead_time": lead_time_days})
    return {"ok": True, "vendor": name}

@tool(name="vendor.reorder_check", description="Check which products are low on inventory and need reordering.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="vendor_manager")
async def reorder_check() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT name, sku, inventory FROM products WHERE inventory < 10 AND active = 1"))
    return {"ok": True, "low_stock_count": len(rows), "products": rows}
