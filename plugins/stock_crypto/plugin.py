# ====================================================================
# JARVIS OMEGA — Free Finance Plugin (Yahoo + CoinGecko)
# ====================================================================
"""
Phase 10 plugin: stock + crypto quotes. No API keys required.

  * ``finance.quote``     — current price for a stock ticker (Yahoo).
  * ``finance.history``   — historical daily prices (Yahoo chart API).
  * ``finance.crypto``    — current price for a crypto coin (CoinGecko).
  * ``finance.trending``  — trending coins (CoinGecko).

Yahoo's unofficial query API is used (``query1.finance.yahoo.com``).
CoinGecko has a generous free tier without authentication.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_YAHOO_BASE = "https://query1.finance.yahoo.com"
_COINGECKO_BASE = "https://api.coingecko.com/api/v3"


@tool(
    name="finance.quote",
    description="Get a current quote for a stock ticker (e.g. 'AAPL', 'MSFT').",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="finance",
)
async def finance_quote(symbol: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_YAHOO_BASE}/v8/finance/chart/{symbol.upper()}",
                params={"range": "1d", "interval": "1m"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("chart", {}).get("result")
        if not data:
            return {"ok": False, "error": f"no data for symbol {symbol}"}
        result = data[0]
        meta = result.get("meta", {})
        return {
            "ok": True,
            "symbol": meta.get("symbol"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "regular_price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("chartPreviousClose"),
            "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
            "regular_day_high": meta.get("regularMarketDayHigh"),
            "regular_day_low": meta.get("regularMarketDayLow"),
            "volume": meta.get("regularMarketVolume"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="finance.history",
    description="Get historical daily prices for a stock ticker.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "range": {"type": "string", "enum": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y", "max"], "default": "1mo"},
            "interval": {"type": "string", "enum": ["1d", "1wk", "1mo"], "default": "1d"},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="finance",
)
async def finance_history(symbol: str, range: str = "1mo", interval: str = "1d") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_YAHOO_BASE}/v8/finance/chart/{symbol.upper()}",
                params={"range": range, "interval": interval},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("chart", {}).get("result")
        if not data:
            return {"ok": False, "error": f"no data for symbol {symbol}"}
        result = data[0]
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators", {}).get("quote", [{}])[0]
        closes = indicators.get("close") or []
        highs = indicators.get("high") or []
        lows = indicators.get("low") or []
        volumes = indicators.get("volume") or []
        candles = []
        for i, ts in enumerate(timestamps):
            candles.append({
                "date": time.strftime("%Y-%m-%d", time.gmtime(ts)),
                "close": closes[i] if i < len(closes) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "volume": volumes[i] if i < len(volumes) else None,
            })
        return {
            "ok": True,
            "symbol": result.get("meta", {}).get("symbol"),
            "currency": result.get("meta", {}).get("currency"),
            "range": range,
            "interval": interval,
            "count": len(candles),
            "candles": candles,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="finance.crypto",
    description="Get current price for a cryptocurrency by CoinGecko coin id (e.g. 'bitcoin', 'ethereum').",
    parameters={
        "type": "object",
        "properties": {
            "coin_id": {"type": "string", "description": "CoinGecko coin id (e.g. 'bitcoin')."},
            "include_marketcup": {"type": "boolean", "default": True},
        },
        "required": ["coin_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="finance",
)
async def finance_crypto(coin_id: str, include_marketcup: bool = True) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
                "include_last_updated_at": "true",
            }
            if include_marketcup:
                params["include_market_cap"] = "true"
            resp = await client.get(
                f"{_COINGECKO_BASE}/simple/price",
                params=params,
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get(coin_id)
        if not data:
            return {"ok": False, "error": f"no data for coin_id '{coin_id}'"}
        return {
            "ok": True,
            "coin_id": coin_id,
            "price_usd": data.get("usd"),
            "market_cap_usd": data.get("usd_market_cap"),
            "volume_24h_usd": data.get("usd_24h_vol"),
            "change_24h_percent": data.get("usd_24h_change"),
            "last_updated": data.get("last_updated_at"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="finance.trending",
    description="List trending cryptocurrencies from CoinGecko.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="finance",
)
async def finance_trending() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_COINGECKO_BASE}/search/trending")
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        coins = resp.json().get("coins", [])
        out = [
            {
                "coin_id": c.get("item", {}).get("id"),
                "name": c.get("item", {}).get("name"),
                "symbol": c.get("item", {}).get("symbol"),
                "market_cap_rank": c.get("item", {}).get("market_cap_rank"),
                "score": c.get("item", {}).get("score"),
            }
            for c in coins
        ]
        return {"ok": True, "count": len(out), "coins": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "stock_crypto"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free stock + crypto quotes (Yahoo + CoinGecko). No API key."
