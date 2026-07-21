# ====================================================================
# JARVIS OMEGA - Trading Plugin (Phase 13) - PAPER-ONLY BY DEFAULT
# ====================================================================
"""
Crypto + stock market data, indicators, and PAPER TRADING.

  trading.quote              - current price (Binance public API via ccxt)
  trading.candles            - historical OHLCV
  trading.indicators         - RSI, MACD, Bollinger, MA (pandas-ta)
  trading.signals_scan       - scan top N coins for buy/sell signals
  trading.backtest           - run a strategy against history
  trading.strategy_dca      - dollar-cost averaging
  trading.strategy_grid     - grid bot
  trading.paper_account     - view paper balance
  trading.paper_buy / sell   - execute simulated trades
  trading.alert_price        - price alert via Telegram/Discord
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("trading")

# Hardcoded list of coins to scan by default (top liquid USDT pairs).
_TOP_COINS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
              "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT", "MATIC/USDT"]


# --------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------

async def _ccxt_fetch(fetcher):
    """Run a sync ccxt call in a thread."""
    try:
        import ccxt  # type: ignore  # noqa: F401
    except ImportError:
        raise RuntimeError("ccxt not installed — add `ccxt` to requirements.txt")
    return await asyncio.to_thread(fetcher)


@tool(
    name="trading.quote",
    description="Get current price for a symbol (e.g. 'BTC/USDT', 'AAPL'). Crypto via ccxt/Binance, stocks via Yahoo.",
    parameters={
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_quote(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper()
    if "/" in symbol:  # Crypto pair
        try:
            def _do():
                exchange = ccxt.binance()
                return exchange.fetch_ticker(symbol)
            import ccxt
            t = await _ccxt_fetch(_do)
            return {
                "ok": True, "symbol": symbol, "price": t.get("last"),
                "bid": t.get("bid"), "ask": t.get("ask"),
                "volume_24h_base": t.get("baseVolume"),
                "change_pct_24h": t.get("percentage"),
                "timestamp": datetime.utcnow().isoformat(),
                "source": "binance",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    # Stock via Yahoo free.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
        data = r.json().get("chart", {}).get("result")
        if not data:
            return {"ok": False, "error": "no data"}
        meta = data[0].get("meta", {})
        return {
            "ok": True, "symbol": symbol, "price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("chartPreviousClose"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "source": "yahoo",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="trading.candles",
    description="Fetch OHLCV candles for a symbol. Returns list of [timestamp, open, high, low, close, volume].",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {"type": "string", "default": "1d", "enum": ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]},
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_candles(symbol: str, timeframe: str = "1d", limit: int = 100) -> Dict[str, Any]:
    try:
        import ccxt
        def _do():
            return ccxt.binance().fetch_ohlcv(symbol.upper(), timeframe=timeframe, limit=limit)
        data = await _ccxt_fetch(_do)
        return {
            "ok": True, "symbol": symbol, "timeframe": timeframe,
            "count": len(data),
            "candles": [
                {"timestamp": datetime.utcfromtimestamp(c[0] / 1000).isoformat(),
                 "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
                for c in data
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Technical indicators
# --------------------------------------------------------------------

@tool(
    name="trading.indicators",
    description="Calculate RSI(14), MACD, Bollinger Bands, SMA(20/50), EMA(12/26) for a symbol.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {"type": "string", "default": "1d"},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_indicators(symbol: str, timeframe: str = "1d") -> Dict[str, Any]:
    try:
        import pandas as pd
        import pandas_ta as ta
    except ImportError as e:
        return {"ok": False, "error": f"{e} — install pandas + pandas-ta"}
    candles = await trading_candles(symbol, timeframe=timeframe, limit=200)
    if not candles.get("ok"):
        return candles
    df = pd.DataFrame(candles["candles"])
    close = df["close"]
    rsi = ta.rsi(close, length=14).iloc[-1]
    macd = ta.macd(close).iloc[-1]
    bb = ta.bbands(close).iloc[-1]
    sma20 = ta.sma(close, length=20).iloc[-1]
    sma50 = ta.sma(close, length=50).iloc[-1]
    return {
        "ok": True, "symbol": symbol, "timeframe": timeframe,
        "last_close": close.iloc[-1],
        "rsi_14": round(rsi, 2),
        "macd": {k: round(v, 4) for k, v in macd.to_dict().items() if not math.isnan(v)},
        "bollinger": {k: round(v, 4) for k, v in bb.to_dict().items() if not math.isnan(v)},
        "sma_20": round(sma20, 4) if not math.isnan(sma20) else None,
        "sma_50": round(sma50, 4) if not math.isnan(sma50) else None,
        "signals": {
            "rsi_oversold": rsi < 30, "rsi_overbought": rsi > 70,
            "above_sma50": close.iloc[-1] > sma50 if not math.isnan(sma50) else None,
        },
    }


@tool(
    name="trading.signals_scan",
    description="Scan top N coins for RSI signals (oversold = potential buy, overbought = potential sell).",
    parameters={
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "default": _TOP_COINS,
            },
            "limit": {"type": "integer", "default": 10},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_signals_scan(symbols: Optional[List[str]] = None, limit: int = 10) -> Dict[str, Any]:
    symbols = symbols or _TOP_COINS[:limit]
    results = []
    for sym in symbols[:limit]:
        ind = await trading_indicators(sym)
        if not ind.get("ok"):
            continue
        rsi = ind["rsi_14"]
        signal = "BUY" if rsi < 30 else "SELL" if rsi > 70 else "HOLD"
        results.append({
            "symbol": sym, "price": ind["last_close"],
            "rsi_14": rsi, "signal": signal,
        })
    results.sort(key=lambda r: (0 if r["signal"] == "BUY" else 1 if r["signal"] == "HOLD" else 2, r["rsi_14"]))
    return {"ok": True, "count": len(results), "results": results}


# --------------------------------------------------------------------
# Backtest + strategies
# --------------------------------------------------------------------

@tool(
    name="trading.backtest",
    description="Simple backtest: SMA crossover strategy. Returns final equity vs buy-and-hold.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "short_window": {"type": "integer", "default": 20},
            "long_window": {"type": "integer", "default": 50},
            "starting_capital_usd": {"type": "number", "default": 10000},
            "timeframe": {"type": "string", "default": "1d"},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_backtest(
    symbol: str, short_window: int = 20, long_window: int = 50,
    starting_capital_usd: float = 10000, timeframe: str = "1d",
) -> Dict[str, Any]:
    try:
        import pandas as pd
    except ImportError as e:
        return {"ok": False, "error": str(e)}
    candles = await trading_candles(symbol, timeframe=timeframe, limit=max(long_window * 3, 200))
    if not candles.get("ok"):
        return candles
    df = pd.DataFrame(candles["candles"])
    df["sma_s"] = df["close"].rolling(short_window).mean()
    df["sma_l"] = df["close"].rolling(long_window).mean()
    df["signal"] = (df["sma_s"] > df["sma_l"]).astype(int).diff()

    cash = starting_capital_usd
    position = 0.0
    for _, row in df.iterrows():
        if row["signal"] == 1 and cash > 0:  # buy
            position = cash / row["close"]
            cash = 0
        elif row["signal"] == -1 and position > 0:  # sell
            cash = position * row["close"]
            position = 0
    final_equity = cash + position * df["close"].iloc[-1]
    buy_hold = starting_capital_usd * df["close"].iloc[-1] / df["close"].iloc[0]
    return {
        "ok": True, "symbol": symbol,
        "strategy_return_pct": round((final_equity - starting_capital_usd) / starting_capital_usd * 100, 2),
        "buy_hold_return_pct": round((buy_hold - starting_capital_usd) / starting_capital_usd * 100, 2),
        "final_equity_usd": round(final_equity, 2),
        "starting_capital_usd": starting_capital_usd,
        "outperformed": final_equity > buy_hold,
        "trades": int(df["signal"].abs().sum()),
    }


@tool(
    name="trading.strategy_dca",
    description="Dollar-cost-averaging simulation. Invest fixed amount every N days.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "amount_usd": {"type": "number", "default": 100},
            "interval_days": {"type": "integer", "default": 7},
            "total_days": {"type": "integer", "default": 365},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_strategy_dca(symbol: str, amount_usd: float = 100, interval_days: int = 7, total_days: int = 365) -> Dict[str, Any]:
    candles = await trading_candles(symbol, timeframe="1d", limit=total_days)
    if not candles.get("ok"):
        return candles
    cs = candles["candles"][::interval_days]
    invested = len(cs) * amount_usd
    coins = sum(amount_usd / c["close"] for c in cs)
    final_value = coins * cs[-1]["close"] if cs else 0
    return {
        "ok": True, "symbol": symbol,
        "purchases": len(cs),
        "total_invested_usd": round(invested, 2),
        "final_value_usd": round(final_value, 2),
        "return_pct": round((final_value - invested) / invested * 100, 2) if invested else 0,
        "avg_buy_price": round(invested / coins, 2) if coins else 0,
    }


@tool(
    name="trading.strategy_grid",
    description="Grid strategy: buy low / sell high in bands. Backtest over historical data.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "num_grids": {"type": "integer", "default": 10},
            "starting_capital_usd": {"type": "number", "default": 10000},
            "total_days": {"type": "integer", "default": 90},
        },
        "required": ["symbol"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_strategy_grid(symbol: str, num_grids: int = 10, starting_capital_usd: float = 10000, total_days: int = 90) -> Dict[str, Any]:
    candles = await trading_candles(symbol, timeframe="1d", limit=total_days)
    if not candles.get("ok"):
        return candles
    cs = [c["close"] for c in candles["candles"]]
    lo, hi = min(cs), max(cs)
    grids = [lo + (hi - lo) * i / num_grids for i in range(num_grids + 1)]
    cash = starting_capital_usd
    coins = 0.0
    last_grid_idx = 0
    for price in cs:
        idx = min(range(len(grids)), key=lambda i: abs(grids[i] - price))
        if idx < last_grid_idx and cash > 0:  # buy
            coins += cash / price
            cash = 0
        elif idx > last_grid_idx and coins > 0:  # sell
            cash = coins * price
            coins = 0
        last_grid_idx = idx
    final = cash + coins * cs[-1]
    return {
        "ok": True, "symbol": symbol,
        "grid_low": round(lo, 2), "grid_high": round(hi, 2),
        "num_grids": num_grids,
        "final_equity_usd": round(final, 2),
        "starting_capital_usd": starting_capital_usd,
        "return_pct": round((final - starting_capital_usd) / starting_capital_usd * 100, 2),
    }


# --------------------------------------------------------------------
# Paper account (simulated trades)
# --------------------------------------------------------------------

PAPER_STARTING_BALANCE = 10000.0


def _ensure_paper_account() -> int:
    row = business_db.query_one("SELECT id FROM paper_account ORDER BY id DESC LIMIT 1")
    if row:
        return row["id"]
    aid = business_db.execute(
        "INSERT INTO paper_account (balance_usd, starting_balance_usd, currency, created_at) VALUES (?, ?, 'USD', ?)",
        (PAPER_STARTING_BALANCE, PAPER_STARTING_BALANCE, datetime.utcnow().isoformat()),
    )
    return aid


@tool(
    name="trading.paper_account",
    description="View the paper-trading account: starting balance, current balance, open positions, P&L.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="trading",
)
async def trading_paper_account() -> Dict[str, Any]:
    aid = _ensure_paper_account()
    acc = business_db.query_one("SELECT * FROM paper_account WHERE id = ?", (aid,))
    trades = business_db.rows_to_dicts(business_db.query(
        "SELECT * FROM paper_trades WHERE timestamp >= ? ORDER BY id DESC LIMIT 100",
        ((datetime.utcnow() - timedelta(days=30)).isoformat(),),
    ))
    # Compute positions by replaying trades.
    positions: Dict[str, Dict[str, float]] = {}
    for t in trades:
        sym = t["symbol"]
        positions.setdefault(sym, {"qty": 0.0, "cost": 0.0})
        if t["side"] == "buy":
            positions[sym]["qty"] += t["quantity"]
            positions[sym]["cost"] += t["quantity"] * t["price_usd"]
        else:
            positions[sym]["qty"] -= t["quantity"]
            positions[sym]["cost"] -= t["quantity"] * t["price_usd"]
    open_positions = [
        {"symbol": s, "quantity": p["qty"], "avg_cost": (p["cost"] / p["qty"] if p["qty"] else 0)}
        for s, p in positions.items() if abs(p["qty"]) > 1e-9
    ]
    return {
        "ok": True, "account_id": aid,
        "starting_balance_usd": acc["starting_balance_usd"],
        "cash_balance_usd": acc["balance_usd"],
        "open_positions": open_positions,
        "mode": "PAPER (simulated)",
    }


@tool(
    name="trading.paper_buy",
    description="Execute a PAPER buy. Deducts from cash balance, adds position. NO REAL MONEY.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "amount_usd": {"type": "number"},
        },
        "required": ["symbol", "amount_usd"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="trading",
)
async def trading_paper_buy(symbol: str, amount_usd: float) -> Dict[str, Any]:
    sym = symbol.upper()
    quote = await trading_quote(sym)
    if not quote.get("ok"):
        return quote
    price = quote["price"]
    qty = amount_usd / price
    aid = _ensure_paper_account()
    acc = business_db.query_one("SELECT balance_usd FROM paper_account WHERE id = ?", (aid,))
    if acc["balance_usd"] < amount_usd:
        return {"ok": False, "error": f"insufficient paper balance: {acc['balance_usd']} < {amount_usd}"}
    business_db.execute(
        "UPDATE paper_account SET balance_usd = balance_usd - ? WHERE id = ?",
        (amount_usd, aid),
    )
    business_db.execute(
        "INSERT INTO paper_trades (symbol, side, quantity, price_usd, timestamp) VALUES (?, 'buy', ?, ?, ?)",
        (sym, qty, price, datetime.utcnow().isoformat()),
    )
    return {"ok": True, "mode": "PAPER", "symbol": sym, "quantity": round(qty, 8), "price_usd": price, "spent_usd": amount_usd}


@tool(
    name="trading.paper_sell",
    description="Execute a PAPER sell. Adds to cash balance, removes position. NO REAL MONEY.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "quantity": {"type": "number"},
        },
        "required": ["symbol", "quantity"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="trading",
)
async def trading_paper_sell(symbol: str, quantity: float) -> Dict[str, Any]:
    sym = symbol.upper()
    quote = await trading_quote(sym)
    if not quote.get("ok"):
        return quote
    price = quote["price"]
    proceeds = quantity * price
    aid = _ensure_paper_account()
    business_db.execute(
        "UPDATE paper_account SET balance_usd = balance_usd + ? WHERE id = ?",
        (proceeds, aid),
    )
    business_db.execute(
        "INSERT INTO paper_trades (symbol, side, quantity, price_usd, timestamp) VALUES (?, 'sell', ?, ?, ?)",
        (sym, quantity, price, datetime.utcnow().isoformat()),
    )
    return {"ok": True, "mode": "PAPER", "symbol": sym, "quantity": quantity, "price_usd": price, "proceeds_usd": round(proceeds, 2)}


@tool(
    name="trading.alert_price",
    description="Set a price alert for a symbol. Triggers a Telegram/Discord message when condition met.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "condition": {"type": "string", "enum": ["above", "below"]},
            "target_price": {"type": "number"},
            "channel": {"type": "string", "enum": ["telegram", "discord", "email"], "default": "telegram"},
        },
        "required": ["symbol", "condition", "target_price"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="trading",
)
async def trading_alert_price(symbol: str, condition: str, target_price: float, channel: str = "telegram") -> Dict[str, Any]:
    aid = business_db.execute(
        """INSERT INTO price_alerts (symbol, condition, target_price, channel, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (symbol.upper(), condition, target_price, channel, datetime.utcnow().isoformat()),
    )
    return {
        "ok": True, "alert_id": aid, "symbol": symbol.upper(),
        "condition": condition, "target_price": target_price, "channel": channel,
        "note": "The price-alert background job fires when the condition is met. Run trader.run_alerts to scan immediately.",
    }


@tool(
    name="trading.run_alerts",
    description="Scan all un-triggered price alerts and fire those whose condition is now true.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="trading",
)
async def trading_run_alerts() -> Dict[str, Any]:
    alerts = business_db.rows_to_dicts(business_db.query(
        "SELECT * FROM price_alerts WHERE triggered = 0 LIMIT 50"
    ))
    triggered = 0
    from plugins.marketing.plugin import marketing_post
    for a in alerts:
        q = await trading_quote(a["symbol"])
        if not q.get("ok"):
            continue
        price = q["price"]
        hit = (a["condition"] == "above" and price >= a["target_price"]) or \
              (a["condition"] == "below" and price <= a["target_price"])
        if not hit:
            continue
        business_db.execute(
            "UPDATE price_alerts SET triggered = 1, triggered_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), a["id"]),
        )
        # Fire the alert.
        msg = f"📊 {a['symbol']} just hit {a['condition']} {a['target_price']} (now: {price})"
        try:
            await marketing_post(platform=a["channel"], content=msg)
        except Exception:
            pass
        triggered += 1
    return {"ok": True, "checked": len(alerts), "triggered": triggered}


PLUGIN_NAME = "trading"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Crypto + stock market data, indicators, paper trading, backtests. PAPER-ONLY by default."
