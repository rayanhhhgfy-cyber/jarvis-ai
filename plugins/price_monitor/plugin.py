# JARVIS OMEGA - Price Monitor (Phase 16)
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict
import httpx, re
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="price.track", description="Add a competitor product URL to price-monitor.", parameters={"type":"object","properties":{"our_product":{"type":"string"},"competitor_url":{"type":"string"},"competitor_name":{"type":"string","default":""},"our_price_jod":{"type":"number","default":0}},"required":["our_product","competitor_url"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="price_monitor")
async def price_track(our_product: str, competitor_url: str, competitor_name: str = "", our_price_jod: float = 0) -> Dict[str, Any]:
    try:
        business_db.execute("INSERT OR IGNORE INTO price_monitored_products (our_product_name, competitor_url, competitor_name, our_price_jod, last_checked) VALUES (?, ?, ?, ?, ?)",
            (our_product, competitor_url, competitor_name, our_price_jod, datetime.utcnow().isoformat()))
        return {"ok": True}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="price.scan_all", description="Scan all tracked competitor URLs and extract prices.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="price_monitor")
async def price_scan_all() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT * FROM price_monitored_products"))
    results = []
    for r in rows:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                resp = await c.get(r["competitor_url"], headers={"User-Agent": "Mozilla/5.0"})
            prices = re.findall(r'([\d,]+\.\d{2})\s*(?:JOD|JD)', resp.text)
            found = float(prices[0].replace(",","")) if prices else None
            if found: business_db.execute("UPDATE price_monitored_products SET last_price_jod = ?, last_checked = ? WHERE id = ?", (found, datetime.utcnow().isoformat(), r["id"]))
            results.append({"product": r["our_product_name"], "competitor_price": found, "our_price": r["our_price_jod"]})
        except Exception: continue
    return {"ok": True, "scanned": len(results), "results": results}

@tool(name="price.recommend", description="Recommend your price based on competitor average.", parameters={"type":"object","properties":{"competitor_avg_jod":{"type":"number"},"strategy":{"type":"string","default":"competitive","enum":["undercut","competitive","premium"]}},"required":["competitor_avg_jod"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="price_monitor")
async def price_recommend(competitor_avg_jod: float, strategy: str = "competitive") -> Dict[str, Any]:
    m = {"undercut": 0.85, "competitive": 0.95, "premium": 1.20}
    return {"ok": True, "recommended_price_jod": round(competitor_avg_jod * m[strategy], 2), "strategy": strategy}

PLUGIN_NAME = "price_monitor"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Competitor price tracking + recommendations."
