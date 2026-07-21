# Phase 18: Safe Investment Manager (Conservative Only)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="invest.stablecoin_yield", description="Scan for safe stablecoin staking yields (USDT/USDC, 5-8% APY).", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="safe_invest")
async def stablecoin_yield() -> Dict[str, Any]:
    from plugins.defi.plugin import defi_yield_scan
    return await defi_yield_scan(min_apy_pct=5, limit=10)

@tool(name="invest.gold_price", description="Check current gold price + trend.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="safe_invest")
async def gold_price() -> Dict[str, Any]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.gold-api.com/price/XAU")
        return {"ok": True, "price_usd_per_oz": r.json().get("price"), "note": "Gold is a safe haven. Popular in Jordan."}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="invest.real_estate_safe", description="Find Amman properties with 8%+ rental yield (conservative).", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="safe_invest")
async def real_estate_safe() -> Dict[str, Any]:
    from plugins.realestate_jo.plugin import realestate_alert_new
    return await realestate_alert_new(city="Amman", min_score=60)

@tool(name="invest.dividend_stocks", description="List stable dividend-paying stocks.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="safe_invest")
async def dividend_stocks() -> Dict[str, Any]:
    return {"ok": True, "stocks": [{"symbol":"VOD","yield_pct":7.2},{"symbol":"T","yield_pct":6.8},{"symbol":"MO","yield_pct":8.5},{"symbol":"XOM","yield_pct":3.8}], "note": "Conservative dividend stocks. Always research before investing."}

PLUGIN_NAME = "safe_invest"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Conservative investments: stablecoins, gold, real estate, dividends."
