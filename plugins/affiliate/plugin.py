# ====================================================================
# JARVIS OMEGA - Affiliate Marketing Plugin (Phase 13)
# ====================================================================
"""
Affiliate networks + content tools.

  affiliate.amazon_search     - PA-API 5 (needs Associates approval)
  affiliate.amazon_earnings   - earnings report
  affiliate.clickbank_products - ClickBank Marketplace (free)
  affiliate.shareasale_offers  - ShareASale feed (free)
  affiliate.link_cloak        - generate redirect on your domain
  affiliate.comparison_table  - LLM "Best X for Y" HTML
  affiliate.review_writer     - LLM product review
  affiliate.disclosure_injector - auto-add legal disclosure
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


# --------------------------------------------------------------------
# Amazon Product Advertising API (PA-API 5)
# --------------------------------------------------------------------

@tool(
    name="affiliate.amazon_search",
    description="Search Amazon products. Requires PA-API credentials (access key, secret, partner tag, host) in vault.",
    parameters={
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "search_index": {"type": "string", "default": "All", "description": "All | Books | Electronics | etc."},
            "item_count": {"type": "integer", "default": 10},
        },
        "required": ["keywords"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="affiliate",
)
async def affiliate_amazon_search(keywords: str, search_index: str = "All", item_count: int = 10) -> Dict[str, Any]:
    access_key = _cred("amazon_pa_access_key")
    secret_key = _cred("amazon_pa_secret_key")
    partner_tag = _cred("amazon_associate_tag")
    host = _cred("amazon_pa_host") or "webservices.amazon.com"
    region = _cred("amazon_pa_region") or "us-east-1"
    if not (access_key and secret_key and partner_tag):
        return {
            "ok": False,
            "error": "PA-API credentials missing (amazon_pa_access_key, amazon_pa_secret_key, amazon_associate_tag).",
        }
    # PA-API v5 requires AWS Signature V4 — use the official amazon-paapi5-sdk.
    try:
        from amazon_paapi5 import DefaultApi, SearchItemsRequest, SearchItemsResource  # type: ignore
        from amazon_paapi5.rest import ApiException  # type: ignore
    except ImportError:
        return {"ok": False, "error": "amazon-paapi-sdk not installed — add `amazon-paapi5-sdk` to requirements.txt"}
    try:
        api = DefaultApi(access_key=access_key, secret_key=secret_key, host=host, region=region)
        req = SearchItemsRequest(
            partner_tag=partner_tag,
            partner_type="Associates",
            keywords=keywords,
            search_index=search_index,
            item_count=min(10, item_count),
            resources=[
                "ItemInfo.Title",
                "ItemInfo.Features",
                "Offers.Listings.Price",
                "Images.Primary.Medium",
            ],
        )
        # SDK is sync; run in thread.
        import asyncio
        def _do():
            return api.search_items(req)
        response = await asyncio.to_thread(_do)
        items = []
        for r in (response.search_result or {}).get("items", []):
            items.append({
                "asin": r.get("ASIN"),
                "title": r.get("itemInfo", {}).get("title", {}).get("displayValue", ""),
                "url": r.get("detailPageURL"),
                "features": r.get("itemInfo", {}).get("features", {}).get("displayValues", []),
                "price": r.get("offers", {}).get("listings", [{}])[0].get("price", {}).get("displayAmount", ""),
                "image": r.get("images", {}).get("primary", {}).get("medium", {}).get("url", ""),
            })
        return {"ok": True, "keywords": keywords, "count": len(items), "products": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="affiliate.amazon_earnings",
    description="Get Amazon Associates earnings. Requires Associates credentials + scraping of Associates dashboard (no official PA-API for earnings).",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="affiliate",
)
async def affiliate_amazon_earnings() -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "Amazon Associates earnings require scraping the Associates Central dashboard. Use the manual link:",
        "manual_url": "https://affiliate-program.amazon.com/home/reports",
        "note": "For automation, login once via browser, extract the session cookie, store in vault, then re-implement with that cookie.",
    }


# --------------------------------------------------------------------
# ClickBank marketplace
# --------------------------------------------------------------------

@tool(
    name="affiliate.clickbank_products",
    description="Search ClickBank marketplace for digital products with affiliate commissions. Free, no auth.",
    parameters={
        "type": "object",
        "properties": {
            "keywords": {"type": "string", "default": ""},
            "category": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 20},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="affiliate",
)
async def affiliate_clickbank_products(keywords: str = "", category: str = "", limit: int = 20) -> Dict[str, Any]:
    # ClickBank exposes a public JSON marketplace endpoint.
    try:
        params = {"sort": "popularity", "perPage": min(50, limit)}
        if keywords:
            params["keyword"] = keywords
        if category:
            params["cat"] = category
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://accounts.clickbank.com/api/marketplace",
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300], "hint": "ClickBank may require login; alternatively use the affiliate marketplace at https://marketplace.clickbank.com"}
        data = resp.json()
        rows = data.get("data", [])
        out = [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "category": r.get("category"),
                "description": r.get("description"),
                "gravity": r.get("gravity"),
                "commission_pct": r.get("commissionPercent"),
                "affiliate_url": f"https://hop.clickbank.net/?affiliate=YOURID&vendor={r.get('id')}",
                "hasRecurringProducts": r.get("hasRecurringProducts"),
            }
            for r in rows[:limit]
        ]
        return {"ok": True, "count": len(out), "products": out}
    except Exception as e:
        return {"ok": False, "error": str(e), "hint": "Marketplace also browseable at https://marketplace.clickbank.com"}


# --------------------------------------------------------------------
# ShareASale
# --------------------------------------------------------------------

@tool(
    name="affiliate.shareasale_offers",
    description="List ShareASale merchant offers. Requires shareasale_affiliate_id + shareasale_api_token in vault.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 20},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="affiliate",
)
async def affiliate_shareasale_offers(category: str = "", limit: int = 20) -> Dict[str, Any]:
    aid = _cred("shareasale_affiliate_id")
    token = _cred("shareasale_api_token")
    if not (aid and token):
        return {
            "ok": False,
            "error": "shareasale_affiliate_id + shareasale_api_token missing in vault",
            "manual_url": "https://account.shareasale.com/a-merchants.cfm",
        }
    try:
        params = {
            "action": "merchantsbycategory",
            "affiliateID": aid,
            "token": token,
            "format": "json",
        }
        if category:
            params["category"] = category
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get("https://api.shareasale.com/w.cfm", params=params)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        return {"ok": True, "count": len(data[:limit]) if isinstance(data, list) else 0, "merchants": data[:limit] if isinstance(data, list) else data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Link cloaking
# --------------------------------------------------------------------

@tool(
    name="affiliate.link_cloak",
    description="Generate an HTML redirect page that cloaks an affiliate link with a clean URL on your domain.",
    parameters={
        "type": "object",
        "properties": {
            "destination_url": {"type": "string"},
            "slug": {"type": "string", "description": "Filename (without .html). e.g. 'best-coffee-machine'."},
            "output_dir": {"type": "string", "default": "./storage/website/go"},
        },
        "required": ["destination_url", "slug"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="affiliate",
)
async def affiliate_link_cloak(destination_url: str, slug: str, output_dir: str = "./storage/website/go") -> Dict[str, Any]:
    safe_slug = "".join(c for c in slug.lower() if c.isalnum() or c in "-_") or "go"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{safe_slug}.html"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url={destination_url}">
<title>Loading...</title>
<meta name="robots" content="noindex">
</head><body>Redirecting… If nothing happens, <a href="{destination_url}">click here</a>.</body></html>"""
    path.write_text(html, encoding="utf-8")
    return {
        "ok": True,
        "slug": safe_slug,
        "path": str(path),
        "public_url_hint": f"/go/{safe_slug}.html",
        "destination": destination_url,
    }


# --------------------------------------------------------------------
# LLM-powered content
# --------------------------------------------------------------------

async def _llm_generate(system_prompt: str, user_msg: str) -> str:
    from backend.services.llm_service import llm_service
    return await llm_service.get_response(
        user_message=user_msg, system_instructions=system_prompt, inject_memory=False,
    )


@tool(
    name="affiliate.comparison_table",
    description="Generate an HTML 'Best X for Y' comparison table for affiliate content.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "e.g. 'coffee machines'"},
            "use_case": {"type": "string", "description": "e.g. 'small office'"},
            "products": {
                "type": "array",
                "default": [],
                "description": "Optional: list of specific products. Empty = LLM picks 3-5.",
                "items": {"type": "object"},
            },
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["category", "use_case"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="affiliate",
)
async def affiliate_comparison_table(
    category: str, use_case: str,
    products: Optional[List[Dict[str, Any]]] = None,
    language: str = "ar",
) -> Dict[str, Any]:
    products = products or []
    sys_prompt = (
        f"You are an expert reviewer. Generate a comparison table HTML snippet for "
        f"'Best {category} for {use_case}' in {'Arabic' if language == 'ar' else 'English'}. "
        f"{'Use the provided products.' if products else 'Pick 3-5 top products with realistic specs.'}"
        "Include columns: Product, Rating, Key Feature, Price Range, Best For, Affiliate Link placeholder."
        "Output only the HTML table — no preamble."
    )
    user_msg = f"Category: {category}\nUse case: {use_case}\n"
    if products:
        user_msg += f"Products: {products}"
    try:
        return {"ok": True, "html_table": await _llm_generate(sys_prompt, user_msg)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="affiliate.review_writer",
    description="Generate a long-form product review article (markdown).",
    parameters={
        "type": "object",
        "properties": {
            "product_name": {"type": "string"},
            "key_features": {"type": "array", "items": {"type": "string"}, "default": []},
            "target_audience": {"type": "string", "default": "general consumers"},
            "tone": {"type": "string", "default": "balanced honest reviewer"},
            "word_count": {"type": "integer", "default": 800},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["product_name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="affiliate",
)
async def affiliate_review_writer(
    product_name: str, key_features: Optional[List[str]] = None,
    target_audience: str = "general consumers",
    tone: str = "balanced honest reviewer",
    word_count: int = 800, language: str = "ar",
) -> Dict[str, Any]:
    key_features = key_features or []
    sys_prompt = (
        f"You are {tone}. Write a {word_count}-word product review for "
        f"{product_name} aimed at {target_audience} in {'Arabic' if language == 'ar' else 'English'}. "
        "Include: TL;DR verdict, pros, cons, who should buy, alternatives. "
        "Output Markdown only. End with a clear affiliate CTA placeholder."
    )
    user_msg = f"Product: {product_name}\nKey features: {key_features}\n"
    try:
        return {"ok": True, "review_markdown": await _llm_generate(sys_prompt, user_msg)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="affiliate.disclosure_injector",
    description="Append a legally-compliant affiliate disclosure to content.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en", "both"]},
        },
        "required": ["content"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="affiliate",
)
async def affiliate_disclosure_injector(content: str, language: str = "ar") -> Dict[str, Any]:
    disclosures = {
        "ar": (
            "\n\n---\n\n"
            "*إفصاح: بعض الروابط في هذه الصفحة هي روابط تابعة. إذا قمت بالشراء عبرها،"
            " قد نتلقى عمولة دون أي تكلفة إضافية عليك. شكراً لدعمك.*"
        ),
        "en": (
            "\n\n---\n\n"
            "*Disclosure: Some links on this page are affiliate links. If you buy through "
            "them, we may earn a commission at no extra cost to you. Thanks for your support.*"
        ),
    }
    suffix = ""
    if language in ("ar", "both"):
        suffix += disclosures["ar"]
    if language in ("en", "both"):
        suffix += ("\n\n" if suffix else "") + disclosures["en"]
    return {"ok": True, "content_with_disclosure": content + suffix}


PLUGIN_NAME = "affiliate"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Amazon PA-API + ClickBank + ShareASale + review writers + link cloaking + disclosure."
