# ====================================================================
# JARVIS OMEGA - DeFi Yield Optimizer (Phase 14)
# ====================================================================
"""
Crypto yield optimization — track + (gated) execute real-money strategies.

🔒 All real-money tools require wallet_private_key + execute_real_trade=true.

  defi.yield_scan              - top 50 yield pools via DeFiLlama
  defi.wallet_balance_multi    - aggregate across chains
  defi.stake_solana            - stake SOL via Marinade (gated)
  defi.farm_ethereum           - Lido stETH (gated)
  defi.auto_compound           - scheduler-friendly compound check
  defi.tax_lots                - cost basis tracking
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


def _real_money_unlocked() -> bool:
    return bool(_cred("wallet_private_key")) and getattr(settings, "execute_real_trade", False)


@tool(
    name="defi.yield_scan",
    description="Scan DeFiLlama for top yield opportunities across all chains. Free, no auth.",
    parameters={
        "type": "object",
        "properties": {
            "chain": {"type": "string", "default": "", "description": "Empty = all chains. e.g. 'Solana', 'Ethereum', 'Arbitrum'."},
            "min_tvl_usd": {"type": "number", "default": 1_000_000},
            "min_apy_pct": {"type": "number", "default": 5},
            "limit": {"type": "integer", "default": 20},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="defi",
)
async def defi_yield_scan(
    chain: str = "", min_tvl_usd: float = 1_000_000, min_apy_pct: float = 5, limit: int = 20,
) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get("https://yields.llama.fi/pools")
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": "DeFiLlama unavailable"}
        pools = resp.json().get("data", [])
        # Filter.
        filtered = []
        for p in pools:
            if chain and p.get("chain") != chain:
                continue
            try:
                tvl = float(p.get("tvlUsd", 0))
                apy = float(p.get("apy", 0) or 0)
            except Exception:
                continue
            if tvl < min_tvl_usd or apy < min_apy_pct:
                continue
            filtered.append({
                "pool": p.get("symbol", ""),
                "project": p.get("project", ""),
                "chain": p.get("chain", ""),
                "tvl_usd": round(tvl, 0),
                "apy_pct": round(apy, 2),
                "stablecoin": p.get("stablecoin", False),
            })
        filtered.sort(key=lambda x: -x["apy_pct"])
        return {"ok": True, "chain": chain or "all", "count": len(filtered[:limit]), "pools": filtered[:limit]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="defi.wallet_balance_multi",
    description="Aggregate wallet balance across Ethereum, Solana, Arbitrum, Base. Read-only — no signing.",
    parameters={
        "type": "object",
        "properties": {
            "wallet_address": {"type": "string", "default": "", "description": "Empty = use eth_wallet_address from vault."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="defi",
)
async def defi_wallet_balance_multi(wallet_address: str = "") -> Dict[str, Any]:
    addr = wallet_address or _cred("eth_wallet_address")
    if not addr:
        return {"ok": False, "error": "wallet address required (param or eth_wallet_address in vault)"}
    balances = {}
    # Use free APIs: Zapper / DeBank have paid tiers; we use chain-native public RPCs.
    # Ethereum balance via etherscan free.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            eth_resp = await client.get(
                "https://api.etherscan.io/api",
                params={"module": "account", "action": "balance", "address": addr, "tag": "latest"},
            )
            if eth_resp.status_code == 200:
                wei = int(eth_resp.json().get("result", 0))
                balances["ethereum_eth"] = round(wei / 1e18, 4)
    except Exception:
        pass
    return {
        "ok": True, "wallet": addr,
        "balances": balances,
        "note": "Limited to Ethereum mainnet for now. Add SOL/ARB/BASE via their RPCs.",
    }


@tool(
    name="defi.stake_solana",
    description="🔒 REAL MONEY. Stake SOL via Marinade. Requires wallet_private_key + execute_real_trade=true.",
    parameters={
        "type": "object",
        "properties": {
            "amount_sol": {"type": "number"},
        },
        "required": ["amount_sol"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="defi",
)
async def defi_stake_solana(amount_sol: float) -> Dict[str, Any]:
    if not _real_money_unlocked():
        return {
            "ok": False,
            "error": "Real-trade gate locked. Set wallet_private_key in vault + execute_real_trade=true in .env.",
        }
    return {
        "ok": False,
        "error": "Solana staking via Python requires `solana` + `solders` SDKs + Marinade SDK. Manual path:",
        "manual_url": "https://marinade.finance",
        "amount_sol": amount_sol,
    }


@tool(
    name="defi.farm_ethereum",
    description="🔒 REAL MONEY. Stake ETH via Lido. Requires wallet_private_key + execute_real_trade=true.",
    parameters={
        "type": "object",
        "properties": {
            "amount_eth": {"type": "number"},
        },
        "required": ["amount_eth"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="defi",
)
async def defi_farm_ethereum(amount_eth: float) -> Dict[str, Any]:
    if not _real_money_unlocked():
        return {
            "ok": False,
            "error": "Real-trade gate locked. Set wallet_private_key in vault + execute_real_trade=true in .env.",
        }
    return {
        "ok": False,
        "error": "Lido staking via Python requires web3.py + Lido contract ABI. Manual path:",
        "manual_url": "https://lido.fi",
        "amount_eth": amount_eth,
    }


@tool(
    name="defi.auto_compound",
    description="Check open positions for harvestable rewards. Returns list of actions to take (does NOT auto-execute).",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="defi",
)
async def defi_auto_compound() -> Dict[str, Any]:
    # For safety, this is a read-only scanner that surfaces opportunities.
    scan = await defi_yield_scan(min_apy_pct=10, limit=10)
    if not scan.get("ok"):
        return scan
    return {
        "ok": True,
        "recommended_actions": [
            f"Consider moving idle capital to {p['project']} ({p['chain']}) — {p['apy_pct']}% APY"
            for p in scan["pools"][:5]
        ],
        "note": "Read-only recommendation. Real execution requires defi.stake_solana / farm_ethereum with gates unlocked.",
    }


@tool(
    name="defi.tax_lots",
    description="Track cost basis for tax reporting. Requires manual entry of buy/sell events.",
    parameters={
        "type": "object",
        "properties": {
            "asset": {"type": "string"},
            "action": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {"type": "number"},
            "price_usd": {"type": "number"},
            "date": {"type": "string", "default": ""},
        },
        "required": ["asset", "action", "quantity", "price_usd"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="defi",
)
async def defi_tax_lots(asset: str, action: str, quantity: float, price_usd: float, date: str = "") -> Dict[str, Any]:
    # Persist in family_assets or a separate tax_lots table.
    # For now, log to audit.
    business_db.audit("tax_lot", "defi", target=asset, details={
        "action": action, "qty": quantity, "price": price_usd, "date": date or datetime.utcnow().isoformat(),
    })
    return {
        "ok": True,
        "asset": asset, "action": action,
        "quantity": quantity, "price_usd": price_usd,
        "total_value_usd": quantity * price_usd,
        "date": date or datetime.utcnow().isoformat(),
        "note": "For tax reporting, aggregate these lots at year-end. Cost basis = sum(buys) - sum(sells).",
    }


PLUGIN_NAME = "defi"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "DeFi yield optimizer. Yield scan + wallet balance + gated real-money staking + tax lots."
