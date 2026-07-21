# ====================================================================
# JARVIS OMEGA — Free Maps Plugin (OpenStreetMap)
# ====================================================================
"""
Phase 10 plugin: geocoding, reverse geocoding, POI search via free
OpenStreetMap public APIs. No API keys required.

  * ``maps.geocode``        — address → lat/lon (Nominatim).
  * ``maps.reverse_geocode`` — lat/lon → address (Nominatim).
  * ``maps.search_nearby``   — POIs around a point (Overpass API).
  * ``maps.directions``      — driving/walking/cycling routes (OSRM).

Be considerate of the public Nominatim / Overpass / OSRM instances — they're
free but rate-limited (1 req/sec for Nominatim). For heavy use, self-host.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier


_NOMINATIM = "https://nominatim.openstreetmap.org"
_OVERPASS = "https://overpass-api.de/api/interpreter"
_OSRM = "https://router.project-osrm.org"
_UA = "JARVIS-OMEGA/1.0 (+local-dev)"


@tool(
    name="maps.geocode",
    description="Convert an address to lat/lon. Uses OpenStreetMap Nominatim.",
    parameters={
        "type": "object",
        "properties": {
            "address": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["address"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="maps",
)
async def maps_geocode(address: str, limit: int = 5) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_NOMINATIM}/search",
                params={"q": address, "format": "json", "limit": limit, "addressdetails": 1},
                headers={"User-Agent": _UA},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        results = resp.json()
        out = [
            {
                "display_name": r.get("display_name"),
                "latitude": float(r.get("lat")) if r.get("lat") else None,
                "longitude": float(r.get("lon")) if r.get("lon") else None,
                "type": r.get("type"),
                "address": r.get("address"),
            }
            for r in results
        ]
        return {"ok": True, "address": address, "count": len(out), "results": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="maps.reverse_geocode",
    description="Convert lat/lon to a street address.",
    parameters={
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
        "required": ["latitude", "longitude"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="maps",
)
async def maps_reverse_geocode(latitude: float, longitude: float) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_NOMINATIM}/reverse",
                params={"lat": latitude, "lon": longitude, "format": "json", "addressdetails": 1},
                headers={"User-Agent": _UA},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        return {
            "ok": True,
            "latitude": latitude,
            "longitude": longitude,
            "display_name": data.get("display_name"),
            "address": data.get("address"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="maps.search_nearby",
    description="Search for points of interest around a coordinate. Uses OpenStreetMap Overpass API.",
    parameters={
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "query": {"type": "string", "description": "POI type (e.g. 'restaurant', 'cafe', 'fuel', 'hospital'). See https://wiki.openstreetmap.org/wiki/Map_features for tag names."},
            "radius_m": {"type": "integer", "default": 1000},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["latitude", "longitude", "query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="maps",
)
async def maps_search_nearby(
    latitude: float, longitude: float, query: str, radius_m: int = 1000, limit: int = 20,
) -> Dict[str, Any]:
    # Build Overpass QL.
    q = (
        f"[out:json][timeout:25];"
        f"node(around:{radius_m},{latitude},{longitude})[\"amenity\"=\"{query}\"];"
        f"out center 20;"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_OVERPASS, data={"data": q}, headers={"User-Agent": _UA})
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        elements = resp.json().get("elements", [])
        results = []
        for el in elements[:limit]:
            tags = el.get("tags", {})
            results.append({
                "name": tags.get("name", "(unnamed)"),
                "type": tags.get("amenity", query),
                "latitude": el.get("lat"),
                "longitude": el.get("lon"),
                "phone": tags.get("phone"),
                "website": tags.get("website"),
                "opening_hours": tags.get("opening_hours"),
            })
        return {
            "ok": True,
            "center": {"latitude": latitude, "longitude": longitude},
            "query": query,
            "radius_m": radius_m,
            "count": len(results),
            "results": results,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="maps.directions",
    description="Get a driving / walking / cycling route between two lat/lon points. Uses OSRM public server.",
    parameters={
        "type": "object",
        "properties": {
            "from_latitude": {"type": "number"}, "from_longitude": {"type": "number"},
            "to_latitude": {"type": "number"}, "to_longitude": {"type": "number"},
            "profile": {"type": "string", "enum": ["driving", "walking", "cycling"], "default": "driving"},
        },
        "required": ["from_latitude", "from_longitude", "to_latitude", "to_longitude"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="maps",
)
async def maps_directions(
    from_latitude: float, from_longitude: float,
    to_latitude: float, to_longitude: float,
    profile: str = "driving",
) -> Dict[str, Any]:
    coords = f"{from_longitude},{from_latitude};{to_longitude},{to_latitude}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_OSRM}/route/v1/{profile}/{coords}",
                params={"overview": "false", "steps": "true"},
            )
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        routes = resp.json().get("routes", [])
        if not routes:
            return {"ok": False, "error": "no route found"}
        r = routes[0]
        legs = r.get("legs", [{}])[0]
        steps = [
            {
                "instruction": s.get("maneuver", {}).get("type", "maneuver"),
                "modifier": s.get("maneuver", {}).get("modifier"),
                "name": s.get("name", ""),
                "distance_m": s.get("distance"),
                "duration_s": s.get("duration"),
            }
            for s in legs.get("steps", [])
        ]
        return {
            "ok": True,
            "profile": profile,
            "distance_km": round(r.get("distance", 0) / 1000, 2),
            "duration_minutes": round(r.get("duration", 0) / 60, 1),
            "steps": steps,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "maps"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free maps: geocode, reverse_geocode, search_nearby, directions (OpenStreetMap)."
