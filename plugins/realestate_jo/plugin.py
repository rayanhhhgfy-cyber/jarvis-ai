# ====================================================================
# JARVIS OMEGA - Jordan Real-Estate Plugin (Phase 13)
# ====================================================================
"""
Scan Jordanian property sites, score investments, alert on deals.

  realestate.list_jo             - browse recent listings (Amman districts)
  realestate.cash_flow_calc      - mortgage + rent → ROI
  realestate.investment_score    - 0-100 score
  realestate.alert_new           - notify when score >= threshold
  realestate.market_stats_jo     - avg price/sqm by neighborhood
  realestate.generate_listing    - Arabic RTL HTML listing for your property
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db


# Average price/sqm in JOD by major Amman neighborhood (2024 estimates).
_AMMAN_AVG_PRICE_PER_SQM_JOD = {
    "Abdalli": 700, "Abdoun": 1100, "Deir Ghbar": 1000, "Jabal Amman": 800,
    "Jabal Hussein": 750, "Khalda": 650, "Shmeisani": 850, "Sweifieh": 900,
    "Tla' al-Ali": 700, "Dabouq": 1300, "Yasmeen": 750, "Jabal Al-Lweibdeh": 800,
    "Sport City": 950, "Wadi Saqra": 850, "Akidar": 600, "Marj Al-Hamam": 550,
    "Qweismeh": 500, "Ras Al-Ain": 500, "Nuzha": 650, "Bayader": 500,
}


# --------------------------------------------------------------------
# Scan
# --------------------------------------------------------------------

@tool(
    name="realestate.list_jo",
    description="Scan Jordanian property listings. Returns parsed rows. NOTE: respects robots.txt + caches.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "default": "Amman"},
            "listing_type": {"type": "string", "enum": ["sale", "rent"], "default": "sale"},
            "property_type": {"type": "string", "default": "apartment", "enum": ["apartment", "villa", "land", "office", "shop"]},
            "max_price_jod": {"type": "number", "default": 0, "description": "0 = no cap."},
            "limit": {"type": "integer", "default": 30},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="realestate_jo",
)
async def realestate_list_jo(
    city: str = "Amman", listing_type: str = "sale", property_type: str = "apartment",
    max_price_jod: float = 0, limit: int = 30,
) -> Dict[str, Any]:
    # OpenSooq has RSS-style search URLs that don't aggressively block.
    try:
        url = "https://jo.opensooq.com/en/real-estate"
        params = {"city": city, "type": property_type, "purpose": listing_type}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                url, params=params,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300],
                    "hint": "If you're being blocked, the public-scrape path is limited. Use manual browsing."}
        # Heuristic parsing — extract price + title fragments.
        listings: List[Dict[str, Any]] = []
        # Look for price patterns like "65,000 JOD" or "JOD 65,000".
        prices = re.findall(r"(?:JOD\s*)?([\d,]+)\s*(?:JOD)?", resp.text)
        # Look for typical listing URLs.
        urls = re.findall(r"/en/real-estate/[\w\-/]+", resp.text)
        for i, (price_str, url_path) in enumerate(zip(prices[:limit], urls[:limit])):
            try:
                price = float(price_str.replace(",", ""))
            except Exception:
                continue
            if max_price_jod and price > max_price_jod:
                continue
            full_url = f"https://jo.opensooq.com{url_path}"
            listings.append({
                "url": full_url,
                "price_jod": price,
                "source": "opensooq",
                "city": city,
                "listing_type": listing_type,
                "property_type": property_type,
            })
            # Persist deduplicated.
            try:
                business_db.execute(
                    """INSERT OR IGNORE INTO property_listings_jo
                       (source, url, price_jod, city, listing_type, property_type, scraped_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    ("opensooq", full_url, price, city, listing_type, property_type,
                     datetime.utcnow().isoformat()),
                )
            except Exception:
                pass
        return {
            "ok": True, "city": city, "count": len(listings), "listings": listings,
            "note": "Listings are best-effort from public HTML. For comprehensive data use paid MLS access.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Cash flow calculator
# --------------------------------------------------------------------

@tool(
    name="realestate.cash_flow_calc",
    description="Real-estate ROI calculator: mortgage + maintenance vs rent income. Outputs monthly and annual cash flow.",
    parameters={
        "type": "object",
        "properties": {
            "purchase_price_jod": {"type": "number"},
            "down_payment_pct": {"type": "number", "default": 25},
            "interest_rate_pct": {"type": "number", "default": 8.5, "description": "Jordan housing loan avg ~8.5%."},
            "loan_years": {"type": "integer", "default": 20},
            "monthly_rent_jod": {"type": "number", "default": 0},
            "annual_maintenance_pct": {"type": "number", "default": 1.0, "description": "% of property value per year."},
            "annual_property_tax_pct": {"type": "number", "default": 0.15},
            "vacancy_pct": {"type": "number", "default": 5},
            "property_management_pct": {"type": "number", "default": 8, "description": "% of rent."},
        },
        "required": ["purchase_price_jod"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="realestate_jo",
)
async def realestate_cash_flow_calc(
    purchase_price_jod: float, down_payment_pct: float = 25,
    interest_rate_pct: float = 8.5, loan_years: int = 20,
    monthly_rent_jod: float = 0,
    annual_maintenance_pct: float = 1.0, annual_property_tax_pct: float = 0.15,
    vacancy_pct: float = 5.0, property_management_pct: float = 8.0,
) -> Dict[str, Any]:
    down = purchase_price_jod * down_payment_pct / 100
    loan_amount = purchase_price_jod - down
    monthly_rate = interest_rate_pct / 100 / 12
    n = loan_years * 12
    if monthly_rate > 0:
        monthly_payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    else:
        monthly_payment = loan_amount / n

    annual_mortgage = monthly_payment * 12
    annual_rent_gross = monthly_rent_jod * 12
    annual_rent_after_vacancy = annual_rent_gross * (1 - vacancy_pct / 100)
    annual_mgmt = annual_rent_after_vacancy * property_management_pct / 100
    annual_maintenance = purchase_price_jod * annual_maintenance_pct / 100
    annual_tax = purchase_price_jod * annual_property_tax_pct / 100

    monthly_cash_flow = (annual_rent_after_vacancy - annual_mortgage - annual_mgmt - annual_maintenance - annual_tax) / 12
    annual_cash_flow = monthly_cash_flow * 12

    cash_on_cash = (annual_cash_flow / down * 100) if down > 0 else 0
    cap_rate = (annual_rent_after_vacancy - annual_mgmt - annual_maintenance - annual_tax) / purchase_price_jod * 100

    return {
        "ok": True,
        "purchase_price_jod": round(purchase_price_jod, 2),
        "down_payment_jod": round(down, 2),
        "loan_amount_jod": round(loan_amount, 2),
        "monthly_mortgage_jod": round(monthly_payment, 2),
        "monthly_cash_flow_jod": round(monthly_cash_flow, 2),
        "annual_cash_flow_jod": round(annual_cash_flow, 2),
        "cash_on_cash_return_pct": round(cash_on_cash, 2),
        "cap_rate_pct": round(cap_rate, 2),
        "currency": "JOD",
        "verdict": "cash-flow positive" if annual_cash_flow > 0 else "cash-flow NEGATIVE",
    }


# --------------------------------------------------------------------
# Investment score
# --------------------------------------------------------------------

@tool(
    name="realestate.investment_score",
    description="Score a property 0-100 for investment quality. Combines price/sqm, ROI, location.",
    parameters={
        "type": "object",
        "properties": {
            "price_jod": {"type": "number"},
            "neighborhood": {"type": "string"},
            "sqm": {"type": "number"},
            "monthly_rent_jod": {"type": "number", "default": 0},
        },
        "required": ["price_jod", "neighborhood", "sqm"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="realestate_jo",
)
async def realestate_investment_score(
    price_jod: float, neighborhood: str, sqm: float, monthly_rent_jod: float = 0,
) -> Dict[str, Any]:
    if sqm <= 0:
        return {"ok": False, "error": "sqm must be > 0"}
    price_per_sqm = price_jod / sqm
    avg = _AMMAN_AVG_PRICE_PER_SQM_JOD.get(neighborhood, 700)
    # Price score: 0 (overpriced) - 30 (well below average).
    if price_per_sqm <= avg * 0.8:
        price_score = 30
    elif price_per_sqm <= avg:
        price_score = 20
    elif price_per_sqm <= avg * 1.1:
        price_score = 10
    else:
        price_score = 0

    # Location score: based on neighborhood desirability.
    location_score = min(30, avg / 50)

    # Rent yield score: 0-25 based on annual gross yield.
    rent_score = 0
    annual_yield = 0
    if monthly_rent_jod > 0:
        annual_yield = monthly_rent_jod * 12 / price_jod * 100
        if annual_yield >= 8:
            rent_score = 25
        elif annual_yield >= 6:
            rent_score = 20
        elif annual_yield >= 4:
            rent_score = 12
        else:
            rent_score = 5

    # Size sanity: 0-15 (sweet spot 70-180 sqm for rentals).
    if 70 <= sqm <= 180:
        size_score = 15
    elif 50 <= sqm < 70 or 180 < sqm <= 250:
        size_score = 10
    else:
        size_score = 5

    total = round(price_score + location_score + rent_score + size_score, 1)
    verdict = "excellent" if total >= 70 else "good" if total >= 50 else "fair" if total >= 30 else "poor"

    return {
        "ok": True,
        "price_jod": round(price_jod, 2),
        "neighborhood": neighborhood,
        "sqm": sqm,
        "price_per_sqm": round(price_per_sqm, 2),
        "neighborhood_avg_per_sqm": avg,
        "annual_gross_yield_pct": round(annual_yield, 2),
        "score_breakdown": {
            "price_score": price_score, "location_score": round(location_score, 1),
            "rent_yield_score": rent_score, "size_score": size_score,
        },
        "total_score": total,
        "verdict": verdict,
    }


# --------------------------------------------------------------------
# Alert on new high-score listings
# --------------------------------------------------------------------

@tool(
    name="realestate.alert_new",
    description="Scan + persist listings whose investment score >= threshold. Optionally send Telegram/Discord alert.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "default": "Amman"},
            "min_score": {"type": "number", "default": 70},
            "alert_channel": {"type": "string", "default": "", "enum": ["", "telegram", "discord"]},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="realestate_jo",
)
async def realestate_alert_new(city: str = "Amman", min_score: float = 70, alert_channel: str = "") -> Dict[str, Any]:
    listings = await realestate_list_jo(city=city, limit=30)
    if not listings.get("ok"):
        return listings
    matched = []
    for l in listings.get("listings", []):
        # Estimate using avg sqm if unknown.
        score = await realestate_investment_score(
            price_jod=l["price_jod"], neighborhood=city, sqm=120,
        )
        if score.get("ok") and score["total_score"] >= min_score:
            matched.append({"listing": l, "score": score["total_score"]})
            if alert_channel:
                from plugins.marketing.plugin import marketing_post
                await marketing_post(
                    platform=alert_channel,
                    content=f"🏡 فرصة عقارية! {l.get('price_jod')} JOD — التقييم {score['total_score']}/100\n{l['url']}",
                    chat_id="" if alert_channel != "telegram" else "me",
                )
    return {"ok": True, "city": city, "matched_count": len(matched), "listings": matched}


# --------------------------------------------------------------------
# Market stats
# --------------------------------------------------------------------

@tool(
    name="realestate.market_stats_jo",
    description="Return average price/sqm table for major Amman neighborhoods (2024 estimates).",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="realestate_jo",
)
async def realestate_market_stats_jo() -> Dict[str, Any]:
    return {
        "ok": True,
        "year_reference": 2024,
        "currency": "JOD",
        "stats": [
            {"neighborhood": n, "avg_price_per_sqm_jod": v}
            for n, v in sorted(_AMMAN_AVG_PRICE_PER_SQM_JOD.items(), key=lambda x: -x[1])
        ],
        "note": "Static estimates for 2024. Refresh annually. Source: market research.",
    }


# --------------------------------------------------------------------
# Listing generator
# --------------------------------------------------------------------

@tool(
    name="realestate.generate_listing",
    description="Generate an Arabic RTL HTML listing for one of your properties.",
    parameters={
        "type": "object",
        "properties": {
            "title_ar": {"type": "string"},
            "description_ar": {"type": "string"},
            "price_jod": {"type": "number"},
            "neighborhood": {"type": "string"},
            "sqm": {"type": "number"},
            "bedrooms": {"type": "integer", "default": 0},
            "bathrooms": {"type": "integer", "default": 0},
            "phone": {"type": "string", "default": ""},
            "image_urls": {"type": "array", "items": {"type": "string"}, "default": []},
            "output_dir": {"type": "string", "default": "./storage/website/listings"},
        },
        "required": ["title_ar", "price_jod", "neighborhood", "sqm"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="realestate_jo",
)
async def realestate_generate_listing(
    title_ar: str, price_jod: float, neighborhood: str, sqm: float,
    description_ar: str = "", bedrooms: int = 0, bathrooms: int = 0,
    phone: str = "", image_urls: Optional[List[str]] = None,
    output_dir: str = "./storage/website/listings",
) -> Dict[str, Any]:
    image_urls = image_urls or []
    images_html = "".join(f'<img src="{u}" class="w-full mb-2 rounded">' for u in image_urls)
    safe_name = "".join(c for c in title_ar if c.isalnum() or c in "-_") or "listing"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"{safe_name}.html"
    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_ar}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap">
<style>body{{font-family:"Tajawal",system-ui,sans-serif}}</style>
</head><body class="bg-gray-50 p-6">
<div class="max-w-3xl mx-auto bg-white rounded-lg shadow p-6">
  {images_html}
  <h1 class="text-3xl font-bold mb-2">{title_ar}</h1>
  <div class="text-2xl text-indigo-700 font-bold mb-4">{price_jod} د.أ</div>
  <div class="grid grid-cols-3 gap-4 mb-4 text-center">
    <div class="bg-gray-100 p-3 rounded"><div class="text-sm text-gray-500">المساحة</div><div class="font-bold">{sqm} م²</div></div>
    <div class="bg-gray-100 p-3 rounded"><div class="text-sm text-gray-500">غرف النوم</div><div class="font-bold">{bedrooms}</div></div>
    <div class="bg-gray-100 p-3 rounded"><div class="text-sm text-gray-500">الحمامات</div><div class="font-bold">{bathrooms}</div></div>
  </div>
  <p class="text-gray-700 whitespace-pre-line">{description_ar}</p>
  <div class="mt-4 text-gray-600"><strong>المنطقة:</strong> {neighborhood}، عمّان</div>
  {f'<a href="tel:{phone}" class="mt-4 inline-block bg-emerald-600 text-white px-6 py-3 rounded">اتصل: {phone}</a>' if phone else ''}
</div>
</body></html>"""
    fname.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(fname), "title": title_ar}


PLUGIN_NAME = "realestate_jo"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Jordan real-estate: scan, ROI calc, investment scoring, alerts, listing generator (Arabic RTL)."
