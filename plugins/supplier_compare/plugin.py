# Phase 19: Supplier Comparison (REAL)
from __future__ import annotations
import re
from typing import Any, Dict
import httpx
from backend.tools import tool, RiskTier

@tool(name="supplier.compare", description="Search for a product on AliExpress + estimate local Jordanian market price.", parameters={"type":"object","properties":{"product_name":{"type":"string"}},"required":["product_name"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="supplier_compare")
async def compare(product_name: str) -> Dict[str, Any]:
    results = {}
    # AliExpress search
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.google.com/search", params={"q": f"site:aliexpress.com {product_name} price"}, headers={"User-Agent":"Mozilla/5.0"})
        ali_links = list(dict.fromkeys(re.findall(r"(https://www\.aliexpress\.com/item/\d+)", r.text)))[:5]
        results["aliexpress"] = {"found": len(ali_links), "links": ali_links}
    except: results["aliexpress"] = {"error": "search failed"}
    # Local estimate (Amman market typically 1.5-2x AliExpress)
    results["local_estimate"] = {"note": "Jordanian retail is typically 1.5-2x AliExpress price", "suggestion": "Check OpenSooq + local shops for exact comparison"}
    return {"ok": True, "product": product_name, "results": results}

PLUGIN_NAME = "supplier_compare"; PLUGIN_VERSION = "1.0.0"
