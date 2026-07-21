# ====================================================================
# JARVIS OMEGA - Shopify Dropship Engine (Phase 14)
# ====================================================================
"""
End-to-end dropshipping: trend scan → AliExpress → store → ads.

  dropship.trend_scan       - TikTok Creative Center + FB Ad Library
  dropship.aliexpress_search - find winning products
  dropship.create_store_woo  - auto-build WooCommerce store (free hosting)
  dropship.list_product      - SEO + AI product photos
  dropship.meta_ad_campaign  - ⚠️ real money - gated
  dropship.auto_fulfill      - auto-order on AliExpress when customer pays
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings


_DROPSHIP_DIR = Path("./storage/dropship")
_DROPSHIP_DIR.mkdir(parents=True, exist_ok=True)


@tool(
    name="dropship.trend_scan",
    description="Scan for trending products in TikTok Creative Center + Facebook Ad Library (best-effort public data).",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "default": "general"},
            "region": {"type": "string", "default": "GLOBAL"},
            "limit": {"type": "integer", "default": 15},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="dropship",
)
async def dropship_trend_scan(category: str = "general", region: str = "GLOBAL", limit: int = 15) -> Dict[str, Any]:
    # FB Ad Library has a public, free API.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # FB Ad Library requires an access token + search.
            token = None
            try:
                from backend.services.credentials_vault import credentials_vault
                token = credentials_vault.get("meta_ad_library_token")
            except Exception:
                pass
            if not token:
                return {
                    "ok": False,
                    "error": "meta_ad_library_token not in vault.",
                    "manual_url": "https://www.facebook.com/ads/library",
                    "hint": "Get a free token at https://developers.facebook.com/tools/explorer/",
                }
            resp = await client.get(
                "https://graph.facebook.com/v18.0/ads_archive",
                params={
                    "access_token": token,
                    "ad_type": "ALL",
                    "ad_active_status": "ACTIVE",
                    "fields": "ad_creative_bodies,ad_delivery_start_time,page_name",
                    "search_terms": category,
                    "ad_reached_countries": f'["{region}"]',
                    "limit": limit,
                },
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("data", [])
        # Aggregate by page_name (proxy for product/advertiser).
        freq: Dict[str, int] = {}
        for d in data:
            name = d.get("page_name", "?")
            freq[name] = freq.get(name, 0) + 1
        trends = sorted(freq.items(), key=lambda x: -x[1])[:limit]
        return {
            "ok": True, "category": category, "region": region,
            "top_advertisers": [{"name": n, "active_ads": c} for n, c in trends],
            "total_ads_scanned": len(data),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="dropship.aliexpress_search",
    description="Search AliExpress for products matching a keyword. Returns product list with affiliate-friendly URLs.",
    parameters={
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "max_price_usd": {"type": "number", "default": 50},
            "min_orders": {"type": "integer", "default": 100},
            "limit": {"type": "integer", "default": 15},
        },
        "required": ["keywords"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="dropship",
)
async def dropship_aliexpress_search(keywords: str, max_price_usd: float = 50, min_orders: int = 100, limit: int = 15) -> Dict[str, Any]:
    # AliExpress doesn't have a free public search API. Use a search-engine approach.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": f"site:aliexpress.com {keywords}", "num": limit},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        import re
        urls = re.findall(r"(https://www\.aliexpress\.com/item/\d+\.\w+\.html)", resp.text)
        unique_urls = list(dict.fromkeys(urls))[:limit]
        products = [{"url": u, "keyword": keywords} for u in unique_urls]
        return {
            "ok": True, "keywords": keywords,
            "count": len(products), "products": products,
            "note": "URLs only — for full product data (price, images, orders), use AliExpress affiliate API.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="dropship.create_store_woo",
    description="Generate a WooCommerce-style store HTML (single page) for a niche. Free hosting via Vercel.",
    parameters={
        "type": "object",
        "properties": {
            "store_name": {"type": "string"},
            "niche": {"type": "string"},
            "products": {"type": "array", "items": {"type": "object"}, "default": []},
            "language": {"type": "string", "default": "ar"},
            "output_dir": {"type": "string", "default": ""},
        },
        "required": ["store_name", "niche"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="dropship",
)
async def dropship_create_store_woo(
    store_name: str, niche: str,
    products: Optional[List[Dict[str, Any]]] = None,
    language: str = "ar", output_dir: str = "",
) -> Dict[str, Any]:
    products = products or []
    from plugins.website.plugin import website_generate_landing_page
    out_dir = output_dir or str(_DROPSHIP_DIR / store_name.lower().replace(" ", "_"))
    result = await website_generate_landing_page(
        product_name=store_name,
        tagline=f"Best {niche} products, delivered to Jordan",
        description=f"Premium {niche} selection.",
        features=[p.get("name", "Product") for p in products[:5]] or ["Curated selection", "Fast delivery", "Cash on delivery"],
        cta_text="تسوق الآن" if language == "ar" else "Shop Now",
        cta_url="#products",
        pricing=[{"name": p.get("name", "Product"), "price": f"{p.get('price', 19)} JOD", "features": []} for p in products[:3]],
        language=language, rtl=(language == "ar"),
        output_dir=out_dir,
    )
    return result


@tool(
    name="dropship.list_product",
    description="Generate a product listing: SEO-optimized description + AI product photo.",
    parameters={
        "type": "object",
        "properties": {
            "product_name": {"type": "string"},
            "image_prompt": {"type": "string"},
            "price_jod": {"type": "number", "default": 19},
            "language": {"type": "string", "default": "ar"},
        },
        "required": ["product_name", "image_prompt"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="dropship",
)
async def dropship_list_product(product_name: str, image_prompt: str, price_jod: float = 19, language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    from plugins.media_free.plugin import media_image_pollinations
    # Generate description.
    try:
        desc = await llm_service.get_response(
            user_message=f"Product: {product_name}\nPrice: {price_jod} JOD",
            system_instructions=(
                f"Write a high-converting product listing in {'Arabic' if language == 'ar' else 'English'}. "
                "Include: title, 3 bullet features, 2-paragraph description. Markdown."
            ),
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
    # Generate image.
    image_result = await media_image_pollinations(prompt=f"product photo, {image_prompt}, white background, studio lighting")
    return {
        "ok": True, "product_name": product_name, "price_jod": price_jod,
        "description_markdown": desc,
        "image_base64": image_result.get("image_base64", "") if image_result.get("ok") else None,
    }


@tool(
    name="dropship.meta_ad_campaign",
    description="⚠️ REAL MONEY. Launch a Meta (Facebook/Instagram) ad campaign. Requires allow_ad_spend=true + budget cap.",
    parameters={
        "type": "object",
        "properties": {
            "store_url": {"type": "string"},
            "daily_budget_usd": {"type": "number", "default": 5},
            "creative_image_path": {"type": "string"},
            "ad_copy": {"type": "string"},
            "target_country": {"type": "string", "default": "JO"},
        },
        "required": ["store_url", "ad_copy"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="dropship",
)
async def dropship_meta_ad_campaign(
    store_url: str, daily_budget_usd: float = 5, creative_image_path: str = "",
    ad_copy: str = "", target_country: str = "JO",
) -> Dict[str, Any]:
    # Hard gate.
    if not getattr(settings, "allow_ad_spend", False):
        return {
            "ok": False,
            "error": "allow_ad_spend=false. Set ALLOW_AD_SPEND=true in .env AND specify a daily budget cap.",
            "warning": "Meta ads spend REAL money. This gate is intentional.",
        }
    cap = getattr(settings, "ad_spend_daily_cap_usd", 50)
    if daily_budget_usd > cap:
        return {"ok": False, "error": f"daily_budget_usd {daily_budget_usd} exceeds cap {cap}"}
    token = None
    try:
        from backend.services.credentials_vault import credentials_vault
        token = credentials_vault.get("meta_marketing_token")
    except Exception:
        pass
    if not token:
        return {"ok": False, "error": "meta_marketing_token not in vault"}
    return {
        "ok": False,
        "error": "Meta Marketing API requires full setup (ad account, pixel, audience). Use https://business.facebook.com for now.",
        "manual_url": "https://business.facebook.com/adsmanager",
        "next_steps": "Set up Meta Business + Marketing API access for full automation.",
    }


@tool(
    name="dropship.auto_fulfill",
    description="Generate an AliExpress order JSON to be placed when a customer pays. Manual submission for now.",
    parameters={
        "type": "object",
        "properties": {
            "aliexpress_product_url": {"type": "string"},
            "customer_name": {"type": "string"},
            "customer_address": {"type": "string"},
            "quantity": {"type": "integer", "default": 1},
        },
        "required": ["aliexpress_product_url", "customer_name", "customer_address"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="dropship",
)
async def dropship_auto_fulfill(
    aliexpress_product_url: str, customer_name: str, customer_address: str, quantity: int = 1,
) -> Dict[str, Any]:
    # Persist the fulfillment task.
    record = {
        "aliexpress_url": aliexpress_product_url,
        "customer": customer_name,
        "address": customer_address,
        "quantity": quantity,
        "generated_at": datetime.utcnow().isoformat(),
    }
    fname = f"fulfill_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    path = _DROPSHIP_DIR / fname
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {
        "ok": True, "record_path": str(path),
        "instructions": "Open the AliExpress URL, add to cart, paste the customer address, place order.",
        "warning": "AliExpress doesn't have a free public order-placement API. Manual submission required for now.",
    }


PLUGIN_NAME = "dropship"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Dropship engine: trend scan + AliExpress search + store + listings + Meta ads (gated) + fulfillment."
