# ====================================================================
# JARVIS OMEGA - Free Weather Plugin (Open-Meteo, no API key)
# ====================================================================
"""
Phase 10 plugin: weather forecasts via Open-Meteo. Free, no key.

  * ``weather.now``      - current conditions at a lat/lon.
  * ``weather.forecast`` - hourly or daily forecast.
  * ``weather.geocode``  - convert a place name to lat/lon (Open-Meteo's
                           free geocoding API).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# WMO weather interpretation codes — human-readable.
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


@tool(
    name="weather.geocode",
    description="Convert a place name to latitude / longitude.",
    parameters={
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "City or place name."},
            "country": {"type": "string", "default": "", "description": "Optional country filter."},
        },
        "required": ["place"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="weather",
)
async def weather_geocode(place: str, country: str = "") -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {"name": place, "count": 5, "language": "en", "format": "json"}
            if country:
                params["country"] = country
            resp = await client.get(_GEOCODE_URL, params=params)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json().get("results", [])
        results = [
            {
                "name": r.get("name"),
                "country": r.get("country"),
                "admin1": r.get("admin1"),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "timezone": r.get("timezone"),
            }
            for r in data
        ]
        return {"ok": True, "place": place, "count": len(results), "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _geocode_one(place: str) -> Optional[Dict[str, Any]]:
    """Helper: return the top geocoding result for a place name."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_GEOCODE_URL, params={"name": place, "count": 1})
        results = resp.json().get("results") or []
        return results[0] if results else None
    except Exception:
        return None


@tool(
    name="weather.now",
    description="Get current weather at a place name or lat/lon. Returns temperature, wind, humidity, and a human-readable condition.",
    parameters={
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "City name (will be geocoded)."},
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="weather",
)
async def weather_now(place: str = "", latitude: Optional[float] = None, longitude: Optional[float] = None) -> Dict[str, Any]:
    if latitude is None or longitude is None:
        if not place:
            return {"ok": False, "error": "either place or latitude+longitude required"}
        geo = await _geocode_one(place)
        if not geo:
            return {"ok": False, "error": f"could not geocode '{place}'"}
        latitude = geo["latitude"]
        longitude = geo["longitude"]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_FORECAST_URL, params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                           "weather_code,wind_speed_10m,wind_direction_10m,precipitation",
                "timezone": "auto",
            })
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        cur = resp.json().get("current", {})
        code = cur.get("weather_code")
        return {
            "ok": True,
            "place": place,
            "latitude": latitude,
            "longitude": longitude,
            "temperature_c": cur.get("temperature_2m"),
            "feels_like_c": cur.get("apparent_temperature"),
            "humidity_percent": cur.get("relative_humidity_2m"),
            "wind_kph": cur.get("wind_speed_10m"),
            "wind_direction": cur.get("wind_direction_10m"),
            "precipitation_mm": cur.get("precipitation"),
            "weather_code": code,
            "condition": WMO_CODES.get(code, "Unknown"),
            "time": cur.get("time"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="weather.forecast",
    description="Get hourly or daily forecast for a place (defaults to 3-day daily forecast).",
    parameters={
        "type": "object",
        "properties": {
            "place": {"type": "string"},
            "days": {"type": "integer", "default": 3, "description": "1-16"},
            "hourly": {"type": "boolean", "default": False, "description": "Return hourly instead of daily."},
        },
        "required": ["place"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="weather",
)
async def weather_forecast(place: str, days: int = 3, hourly: bool = False) -> Dict[str, Any]:
    geo = await _geocode_one(place)
    if not geo:
        return {"ok": False, "error": f"could not geocode '{place}'"}
    lat, lon = geo["latitude"], geo["longitude"]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {
                "latitude": lat, "longitude": lon,
                "timezone": "auto",
                "forecast_days": max(1, min(16, days)),
            }
            if hourly:
                params["hourly"] = "temperature_2m,weather_code,precipitation_probability"
            else:
                params["daily"] = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
            resp = await client.get(_FORECAST_URL, params=params)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        out: Dict[str, Any] = {
            "ok": True,
            "place": place,
            "latitude": lat,
            "longitude": lon,
        }
        if hourly:
            h = data.get("hourly", {})
            times = h.get("time", [])
            temps = h.get("temperature_2m", [])
            codes = h.get("weather_code", [])
            pops = h.get("precipitation_probability", [])
            hours = []
            for i, t in enumerate(times):
                hours.append({
                    "time": t,
                    "temperature_c": temps[i] if i < len(temps) else None,
                    "condition": WMO_CODES.get(codes[i] if i < len(codes) else None, "Unknown"),
                    "precipitation_probability": pops[i] if i < len(pops) else None,
                })
            out["hours"] = hours
            out["count"] = len(hours)
        else:
            d = data.get("daily", {})
            times = d.get("time", [])
            tmax = d.get("temperature_2m_max", [])
            tmin = d.get("temperature_2m_min", [])
            codes = d.get("weather_code", [])
            pops = d.get("precipitation_sum", [])
            winds = d.get("wind_speed_10m_max", [])
            days_out = []
            for i, t in enumerate(times):
                days_out.append({
                    "date": t,
                    "temp_max_c": tmax[i] if i < len(tmax) else None,
                    "temp_min_c": tmin[i] if i < len(tmin) else None,
                    "condition": WMO_CODES.get(codes[i] if i < len(codes) else None, "Unknown"),
                    "precipitation_mm": pops[i] if i < len(pops) else None,
                    "wind_max_kph": winds[i] if i < len(winds) else None,
                })
            out["days"] = days_out
            out["count"] = len(days_out)
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "weather"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free weather via Open-Meteo (current + forecast + geocoding). No API key."
