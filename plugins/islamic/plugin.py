# ====================================================================
# JARVIS OMEGA - Islamic Tools Plugin (Phase 13)
# ====================================================================
"""
Daily-use Islamic utilities for Sir. All free public APIs.

  islamic.prayer_times      - accurate salah times for any city
  islamic.hijri_date        - Gregorian → Hijri (Umm al-Qura)
  islamic.quran_lookup      - ayah by surah:ayah reference (Arabic + translations)
  islamic.hadith_search     - hadith by text
  islamic.zakat_calculator  - cash / gold / silver / stocks / business
  islamic.qibla             - bearing from lat/lon to Kaaba
  islamic.halal_check       - ingredient analysis (porcine, alcohol, E-codes)
  islamic.events_calendar   - Ramadan, Eid, Muharram, etc.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Prayer times — Aladhan API (free)
# --------------------------------------------------------------------

@tool(
    name="islamic.prayer_times",
    description="Get prayer times for a city (defaults: Amman, Jordan). Uses Aladhan API.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "default": "Amman"},
            "country": {"type": "string", "default": "Jordan"},
            "method": {
                "type": "integer",
                "default": 3,
                "description": "1=Univ. of Karachi, 2=ISNA, 3=MWL, 4=Umm al-Qura, 5=Egyptian Auth., others see Aladhan docs.",
            },
            "date": {"type": "string", "default": "", "description": "DD-MM-YYYY. Empty = today."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_prayer_times(
    city: str = "Amman", country: str = "Jordan", method: int = 3, date: str = "",
) -> Dict[str, Any]:
    url = "https://api.aladhan.com/v1/timingsByCity"
    params = {"city": city, "country": country, "method": method}
    if date:
        url = f"https://api.aladhan.com/v1/timingsByCity/{date}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("data", {})
        timings = data.get("timings", {})
        # Strip the timezone noise like "(GMT)" from each time.
        cleaned = {k: (v.split(" ")[0] if isinstance(v, str) else v) for k, v in timings.items()}
        return {
            "ok": True,
            "city": city,
            "country": country,
            "date": data.get("date", {}).get("readable", ""),
            "hijri": data.get("date", {}).get("hijri", {}),
            "timings": cleaned,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Hijri date
# --------------------------------------------------------------------

@tool(
    name="islamic.hijri_date",
    description="Convert a Gregorian date to Hijri (Umm al-Qura calendar). Defaults to today.",
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "default": "", "description": "DD-MM-YYYY. Empty = today."},
            "adjustment": {"type": "integer", "default": 0, "description": "±days to adjust Hijri."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_hijri_date(date: str = "", adjustment: int = 0) -> Dict[str, Any]:
    endpoint = f"https://api.aladhan.com/v1/gToH/{date}" if date else "https://api.aladhan.com/v1/gToH"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(endpoint, params={"adjustment": adjustment})
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("data", [])
        item = data[0] if isinstance(data, list) and data else data
        hijri = item.get("hijri", {}) if isinstance(item, dict) else {}
        gregorian = item.get("gregorian", {}) if isinstance(item, dict) else {}
        return {
            "ok": True,
            "hijri_date": hijri.get("date"),
            "hijri_day": hijri.get("day"),
            "hijri_month": hijri.get("month", {}).get("en"),
            "hijri_month_ar": hijri.get("month", {}).get("ar"),
            "hijri_year": hijri.get("year"),
            "weekday_ar": hijri.get("weekday", {}).get("ar"),
            "gregorian_date": gregorian.get("date"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Quran lookup
# --------------------------------------------------------------------

@tool(
    name="islamic.quran_lookup",
    description="Fetch ayah(s) from the Quran. Returns Arabic + English translation.",
    parameters={
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "Format: '2:255' (Ayat al-Kursi) or '1' (whole surah)."},
            "translations": {"type": "array", "items": {"type": "string"}, "default": ["en.sahih"], "description": "e.g. en.sahih, fr.hamidullah"},
        },
        "required": ["reference"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_quran_lookup(reference: str, translations: Optional[List[str]] = None) -> Dict[str, Any]:
    translations = translations or ["en.sahih"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Use the quran.com API v4.
            headers = {"Accept": "application/json"}
            url = f"https://api.quran.com/api/v4/verses/by_key/{reference}"
            params = {
                "words": "false",
                "translations": ",".join(translations),
                "fields": "text_uthmani",
            }
            resp = await client.get(url, params=params, headers=headers)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("verse", {})
        if not data:
            return {"ok": False, "error": "verse not found"}
        return {
            "ok": True,
            "reference": reference,
            "arabic_text": data.get("text_uthmani", ""),
            "surah": data.get("verse_key", "").split(":")[0],
            "ayah": data.get("verse_key", "").split(":")[-1] if ":" in data.get("verse_key", "") else None,
            "translations": {
                t["resource_name"]: t["text"]
                for t in data.get("translations", [])
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Hadith search
# --------------------------------------------------------------------

@tool(
    name="islamic.hadith_search",
    description="Search hadith collections (Bukhari, Muslim, etc.) by text.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "collection": {"type": "string", "default": "all", "description": "bukhari, muslim, abudawud, tirmidhi, nasai, ibnmajah, malik, ahmad, all"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_hadith_search(query: str, collection: str = "all", limit: int = 5) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Use the sunnah.com API v4 via quran.com style endpoints.
            url = "https://api.quran.com/api/v4/search"
            resp = await client.get(url, params={
                "q": query,
                "size": limit,
                "type": "hadith",
                "collection": collection if collection != "all" else None,
            })
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        results = []
        for r in data.get("results", [])[:limit]:
            results.append({
                "collection": r.get("collection"),
                "book": r.get("book"),
                "hadith_number": r.get("hadithNumber"),
                "arabic_text": r.get("arabicText") or r.get("arabic_text"),
                "english_text": r.get("englishText") or r.get("english_text"),
            })
        return {"ok": True, "count": len(results), "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Zakat calculator
# --------------------------------------------------------------------

@tool(
    name="islamic.zakat_calculator",
    description="Calculate zakat due (2.5% on applicable assets above nisab). Nisab defaults: gold=85g, silver=595g.",
    parameters={
        "type": "object",
        "properties": {
            "cash_jod": {"type": "number", "default": 0},
            "gold_grams": {"type": "number", "default": 0},
            "silver_grams": {"type": "number", "default": 0},
            "stocks_value_jod": {"type": "number", "default": 0},
            "business_inventory_jod": {"type": "number", "default": 0},
            "debts_owed_to_you_jod": {"type": "number", "default": 0},
            "debts_you_owe_jod": {"type": "number", "default": 0},
            "gold_price_per_gram_jod": {"type": "number", "default": 45, "description": "Approx JOD/gram 24k. Override with live price."},
            "silver_price_per_gram_jod": {"type": "number", "default": 0.7},
            "annual": {"type": "boolean", "default": True, "description": "True=annual 2.5%, False=monthly prorate."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_zakat_calculator(
    cash_jod: float = 0, gold_grams: float = 0, silver_grams: float = 0,
    stocks_value_jod: float = 0, business_inventory_jod: float = 0,
    debts_owed_to_you_jod: float = 0, debts_you_owe_jod: float = 0,
    gold_price_per_gram_jod: float = 45, silver_price_per_gram_jod: float = 0.7,
    annual: bool = True,
) -> Dict[str, Any]:
    # Nisab: 85g gold OR 595g silver (whichever is more beneficial to payer = silver usually).
    nisab_gold_jod = 85 * gold_price_per_gram_jod
    nisab_silver_jod = 595 * silver_price_per_gram_jod
    nisab = min(nisab_gold_jod, nisab_silver_jod)  # use lower (silver) for payer benefit

    gold_value = gold_grams * gold_price_per_gram_jod
    silver_value = silver_grams * silver_price_per_gram_jod
    total_assets = (cash_jod + gold_value + silver_value + stocks_value_jod
                    + business_inventory_jod + debts_owed_to_you_jod)
    net_assets = total_assets - debts_you_owe_jod

    rate = 0.025 if annual else (0.025 / 12)

    if net_assets < nisab:
        return {
            "ok": True,
            "zakat_due_jod": 0,
            "reason": f"net assets ({net_assets:.2f} JOD) below nisab ({nisab:.2f} JOD)",
            "nisab_used": "silver (lower, payer-favorable)",
            "nisab_value_jod": round(nisab, 2),
            "total_assets_jod": round(total_assets, 2),
            "net_assets_jod": round(net_assets, 2),
        }

    zakat = net_assets * rate
    return {
        "ok": True,
        "zakat_due_jod": round(zakat, 2),
        "currency": "JOD",
        "period": "annual" if annual else "monthly",
        "rate_used": f"{rate*100}%",
        "nisab_used": "silver (lower, payer-favorable)",
        "nisab_value_jod": round(nisab, 2),
        "nisab_gold_jod": round(nisab_gold_jod, 2),
        "nisab_silver_jod": round(nisab_silver_jod, 2),
        "total_assets_jod": round(total_assets, 2),
        "debts_deducted_jod": round(debts_you_owe_jod, 2),
        "net_assets_jod": round(net_assets, 2),
    }


# --------------------------------------------------------------------
# Qibla direction
# --------------------------------------------------------------------

_KAABA_LAT = 21.4225
_KAABA_LON = 39.8262


@tool(
    name="islamic.qibla",
    description="Calculate Qibla bearing (degrees from North, clockwise) from a location.",
    parameters={
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
        "required": ["latitude", "longitude"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_qibla(latitude: float, longitude: float) -> Dict[str, Any]:
    # Great-circle bearing formula.
    phi1 = math.radians(latitude)
    phi2 = math.radians(_KAABA_LAT)
    dlam = math.radians(_KAABA_LON - longitude)
    x = math.sin(dlam) * math.cos(phi2)
    y = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(dlam))
    theta = math.atan2(x, y)
    bearing = (math.degrees(theta) + 360) % 360
    direction = bearing_to_compass(bearing)
    return {
        "ok": True,
        "from": {"latitude": latitude, "longitude": longitude},
        "qibla_bearing_degrees": round(bearing, 2),
        "compass_direction": direction,
        "kaaba": {"latitude": _KAABA_LAT, "longitude": _KAABA_LON},
    }


def bearing_to_compass(b: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((b + 22.5) % 360 / 45)]


# --------------------------------------------------------------------
# Halal ingredient check
# --------------------------------------------------------------------

# Known haram / questionable ingredients. Extend as needed.
_HARAM_INGREDIENTS = {
    # Porcine / pork-derived
    "lard": "porcine fat", "pork": "pork", "bacon": "pork", "ham": "pork",
    "gelatin": "often porcine/bovine — verify source", "rennet": "animal enzyme — verify source",
    "pepsin": "porcine enzyme often", "lipase": "animal enzyme often",
    "shortening": "may be animal-derived — verify", "collagen": "animal source — verify",
    "cysteine": "l-cysteine often from human/duck feathers — verify",
    # Alcohol
    "alcohol": "intoxicant", "ethanol": "intoxicant", "rum": "intoxicant",
    "wine": "intoxicant", "beer": "intoxicant", "brandy": "intoxicant",
    "vodka": "intoxicant", "whisky": "intoxicant", "bourbon": "intoxicant",
    "champagne": "intoxicant", "vanilla extract": "often alcohol-base",
    # Questionable E-codes
    "e120": "carmine (insect-derived)", "e904": "shellac (insect-derived)",
    "e631": "often from pork/fish — verify", "e635": "often from pork/fish — verify",
    "e627": "often from pork/fish — verify", "e471": "may be animal — verify",
    "e472a": "may be animal — verify", "e472b": "may be animal — verify",
    "e472c": "may be animal — verify", "e472d": "may be animal — verify",
    "e472e": "may be animal — verify", "e472f": "may be animal — verify",
    "e474": "may be animal — verify", "e475": "may be animal — verify",
    "e476": "may be animal — verify", "e477": "may be animal — verify",
    "e478": "may be animal — verify", "e479b": "may be animal — verify",
    "e480": "may be animal — verify", "e481": "may be animal — verify",
    "e482": "may be animal — verify", "e483": "may be animal — verify",
    "e491": "may be animal — verify", "e492": "may be animal — verify",
    "e493": "may be animal — verify", "e494": "may be animal — verify",
    "e495": "may be animal — verify",
    "e542": "edible bone phosphate — animal source",
    "e631": "often pork/fish — verify",
    "e635": "often pork/fish — verify",
    "e640": "may be animal — verify",
    "e1518": "glycerol — may be animal — verify",
}


@tool(
    name="islamic.halal_check",
    description="Check an ingredient list for haram/questionable items. Returns findings + verdict.",
    parameters={
        "type": "object",
        "properties": {
            "ingredients_text": {"type": "string", "description": "Full ingredient list from packaging."},
        },
        "required": ["ingredients_text"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_halal_check(ingredients_text: str) -> Dict[str, Any]:
    text = ingredients_text.lower()
    findings: List[Dict[str, str]] = []
    for ing, reason in _HARAM_INGREDIENTS.items():
        if ing in text:
            findings.append({"ingredient": ing, "reason": reason, "severity": "haram" if "intoxicant" in reason or "porcine" in reason or "pork" in reason or "insect" in reason else "questionable"})
    # Verdict logic.
    haram_count = sum(1 for f in findings if f["severity"] == "haram")
    questionable_count = sum(1 for f in findings if f["severity"] == "questionable")
    if haram_count > 0:
        verdict = "haram"
    elif questionable_count > 0:
        verdict = "questionable — verify source"
    else:
        verdict = "halal (no known red flags)"
    return {
        "ok": True,
        "verdict": verdict,
        "haram_count": haram_count,
        "questionable_count": questionable_count,
        "findings": findings,
        "disclaimer": "This is a heuristic check based on common ingredient names. For final certification consult a halal authority.",
    }


# --------------------------------------------------------------------
# Events calendar
# --------------------------------------------------------------------

@tool(
    name="islamic.events_calendar",
    description="List upcoming Islamic events for the next N months (Ramadan, Eid al-Fitr, Eid al-Adha, Islamic New Year, Mawlid, Ashura).",
    parameters={
        "type": "object",
        "properties": {
            "months_ahead": {"type": "integer", "default": 12},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="islamic",
)
async def islamic_events_calendar(months_ahead: int = 12) -> Dict[str, Any]:
    try:
        # Aladhan's Hijri calendar for next N months; filter for notable days.
        today = datetime.utcnow()
        events: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for offset in range(months_ahead + 1):
                # Compute target month
                y, m = today.year + (today.month - 1 + offset) // 12, (today.month - 1 + offset) % 12 + 1
                resp = await client.get(f"https://api.aladhan.com/v1/gToHCalendar/{m:02d}-{y}")
                if resp.status_code >= 400:
                    continue
                for entry in resp.json().get("data", []):
                    hijri = entry.get("hijri", {})
                    gregorian = entry.get("gregorian", {})
                    day = hijri.get("day")
                    month_num = int(hijri.get("month", {}).get("number", 0))
                    # Notable days.
                    notable = []
                    if month_num == 1 and day == "1":  # Muharram 1 — Islamic New Year
                        notable.append("Islamic New Year (Ras as-Sana)")
                    if month_num == 1 and day == "10":  # Ashura
                        notable.append("Ashura (10 Muharram)")
                    if month_num == 3 and day == "12":  # Mawlid an-Nabi (Sunni)
                        notable.append("Mawlid an-Nabi")
                    if month_num == 7 and day == "27":  # Isra and Mi'raj (commonly observed)
                        notable.append("Isra and Mi'raj (observed)")
                    if month_num == 9:  # Ramadan
                        if day == "1":
                            notable.append("First day of Ramadan")
                        if day == "27":
                            notable.append("Laylat al-Qadr (most likely night)")
                    if month_num == 10 and day == "1":
                        notable.append("Eid al-Fitr")
                    if month_num == 12 and day == "9":
                        notable.append("Day of Arafah")
                    if month_num == 12 and day == "10":
                        notable.append("Eid al-Adha")
                    if notable:
                        events.append({
                            "gregorian_date": gregorian.get("date"),
                            "hijri_date": hijri.get("date"),
                            "weekday": gregorian.get("weekday", {}).get("en"),
                            "events": notable,
                        })
        # Sort by Gregorian date.
        events.sort(key=lambda e: e["gregorian_date"] or "")
        return {"ok": True, "count": len(events), "events": events}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "islamic"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Islamic utilities: prayer times, Hijri date, Quran, hadith, zakat, Qibla, halal check, events."
