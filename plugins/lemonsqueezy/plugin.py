# ====================================================================
# JARVIS OMEGA - Lemon Squeezy Payment Processor (Phase 15)
# ====================================================================
"""
Lemon Squeezy = Merchant of Record. Handles VAT, tax, payment processing
globally. Perfect for Jordan (Stripe doesn't support JO).

Money flow: Customer → Lemon Squeezy → YOUR Payoneer/bank (auto-payout)

  lemonsqueezy.create_product    - create a digital product
  lemonsqueezy.create_variant    - add pricing tier
  lemonsqueezy.create_checkout   - generate checkout URL
  lemonsqueezy.list_sales        - recent sales + revenue
  lemonsqueezy.payout_info       - where your money is + when it arrives
  lemonsqueezy.create_store      - set up a new Lemon Squeezy store
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from datetime import datetime


_LS_API = "https://api.lemonsqueezy.com/v1"


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


def _headers() -> Dict[str, str]:
    key = _cred("lemonsqueezy_api_key")
    if not key:
        raise RuntimeError("lemonsqueezy_api_key not in vault. Sign up at https://lemonsqueezy.com")
    return {
        "Accept": "application/vnd.api+json",
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/vnd.api+json",
    }


@tool(
    name="lemonsqueezy.create_product",
    description="Create a digital product on Lemon Squeezy. Returns product ID.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string", "default": ""},
            "store_id": {"type": "string", "default": "", "description": "Empty = use first store."},
            "price_usd": {"type": "number", "default": 19},
        },
        "required": ["name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="lemonsqueezy",
)
async def lemonsqueezy_create_product(name: str, description: str = "", store_id: str = "", price_usd: float = 19) -> Dict[str, Any]:
    try:
        headers = _headers()
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "signup_url": "https://lemonsqueezy.com"}
    # Get store if not provided.
    if not store_id:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{_LS_API}/stores", headers=headers)
                stores = resp.json().get("data", [])
                if not stores:
                    return {"ok": False, "error": "no stores found — create one first at https://lemonsqueezy.com"}
                store_id = stores[0]["id"]
        except Exception as e:
            return {"ok": False, "error": str(e)}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_LS_API}/products",
                headers=headers,
                json={
                    "data": {
                        "type": "products",
                        "attributes": {
                            "name": name,
                            "description": description,
                            "status": "published",
                            "pricing": {"price_cents": int(price_usd * 100), "currency": "USD"},
                        },
                        "relationships": {"store": {"data": {"type": "stores", "id": store_id}}},
                    }
                },
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:400]}
        data = resp.json().get("data", {})
        return {
            "ok": True, "product_id": data.get("id"),
            "name": name, "price_usd": price_usd,
            "store_id": store_id,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="lemonsqueezy.create_checkout",
    description="Generate a checkout URL for a product. Customer pays here.",
    parameters={
        "type": "object",
        "properties": {
            "product_id": {"type": "string"},
            "variant_id": {"type": "string", "default": ""},
        },
        "required": ["product_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="lemonsqueezy",
)
async def lemonsqueezy_create_checkout(product_id: str, variant_id: str = "") -> Dict[str, Any]:
    try:
        headers = _headers()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    # If no variant, get the product's first variant.
    if not variant_id:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_LS_API}/variants",
                    params={"filter[product_id]": product_id},
                    headers=headers,
                )
            variants = resp.json().get("data", [])
            if not variants:
                return {"ok": False, "error": "no variants found for product"}
            variant_id = variants[0]["id"]
        except Exception as e:
            return {"ok": False, "error": str(e)}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_LS_API}/checkouts",
                headers=headers,
                json={
                    "data": {
                        "type": "checkouts",
                        "attributes": {
                            "product_options": {"variant_quantities": [{"variant_id": int(variant_id), "quantity": 1}]},
                        },
                    }
                },
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:400]}
        data = resp.json().get("data", {})
        return {
            "ok": True,
            "checkout_url": data.get("attributes", {}).get("url"),
            "checkout_id": data.get("id"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="lemonsqueezy.list_sales",
    description="List recent sales. Returns total revenue + per-sale breakdown.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="lemonsqueezy",
)
async def lemonsqueezy_list_sales(limit: int = 20) -> Dict[str, Any]:
    try:
        headers = _headers()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_LS_API}/orders",
                params={"per_page": limit, "sort": "-created"},
                headers=headers,
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        orders = resp.json().get("data", [])
        sales = []
        total_cents = 0
        for o in orders:
            attrs = o.get("attributes", {})
            total_cents += attrs.get("total", 0)
            sales.append({
                "order_id": o.get("id"),
                "customer_email": attrs.get("user_email"),
                "total_usd": round(attrs.get("total", 0) / 100, 2),
                "status": attrs.get("status"),
                "date": attrs.get("created_at"),
            })
        return {
            "ok": True,
            "sales": sales,
            "count": len(sales),
            "total_revenue_usd": round(total_cents / 100, 2),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="lemonsqueezy.payout_info",
    description="Check when Lemon Squeezy will pay out + to where.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="lemonsqueezy",
)
async def lemonsqueezy_payout_info() -> Dict[str, Any]:
    return {
        "ok": True,
        "how_it_works": (
            "Lemon Squeezy is a Merchant of Record. They collect payments globally, "
            "handle VAT/tax, then pay you out to your connected account."
        ),
        "payout_schedule": "Monthly (between 11th-15th of each month, for previous month's sales).",
        "minimum_payout": "$5 USD",
        "setup_url": "https://lemonsqueezy.com/settings/billing",
        "for_jordan": (
            "Connect Payoneer (works in Jordan) as your payout method. "
            "Payoneer → local Jordanian bank (Arab Bank, Cairo Amman Bank, etc.) → "
            "then to Zain Cash via your banking app."
        ),
        "zain_cash_flow": "Lemon Squeezy → Payoneer → Jordan bank → Zain Cash",
    }


@tool(
    name="lemonsqueezy.create_store",
    description="Guide: set up a new Lemon Squeezy store. Opens signup in browser.",
    parameters={
        "type": "object",
        "properties": {
            "store_name": {"type": "string"},
        },
        "required": ["store_name"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="lemonsqueezy",
)
async def lemonsqueezy_create_store(store_name: str) -> Dict[str, Any]:
    import webbrowser
    webbrowser.open("https://lemonsqueezy.com/signup")
    return {
        "ok": True,
        "store_name": store_name,
        "signup_url": "https://lemonsqueezy.com/signup",
        "instructions": [
            "1. Sign up at the URL (browser opened).",
            "2. Verify your email.",
            "3. Add your business name + details.",
            "4. Go to Settings → Billing → connect Payoneer (recommended for Jordan).",
            "5. Go to Settings → API → generate API key.",
            "6. Put the API key in the vault as 'lemonsqueezy_api_key'.",
        ],
        "for_jordan_note": "Lemon Squeezy accepts creators from Jordan. Payoneer is the recommended payout method for Jordan.",
    }


PLUGIN_NAME = "lemonsqueezy"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Lemon Squeezy: global Merchant of Record. Handles VAT/tax/payouts. Perfect for Jordan."
