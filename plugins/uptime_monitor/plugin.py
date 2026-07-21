# Phase 18: Uptime Monitor (REAL)
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List
from pathlib import Path
import json
import httpx
from backend.tools import tool, RiskTier

_SITES_PATH = Path("./storage/monitored_sites.json")

def _load_sites():
    if not _SITES_PATH.exists(): return []
    return json.loads(_SITES_PATH.read_text(encoding="utf-8"))

def _save_sites(sites):
    _SITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SITES_PATH.write_text(json.dumps(sites, indent=2), encoding="utf-8")

@tool(name="uptime.add_site", description="Add a URL to uptime monitoring.", parameters={"type":"object","properties":{"url":{"type":"string"},"name":{"type":"string","default":""}},"required":["url"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="uptime_monitor")
async def add_site(url: str, name: str = "") -> Dict[str, Any]:
    sites = _load_sites()
    sites.append({"url": url, "name": name or url, "added_at": datetime.utcnow().isoformat()})
    _save_sites(sites)
    return {"ok": True, "monitoring": url, "total_sites": len(sites)}

@tool(name="uptime.check_all", description="Ping all monitored sites. Returns status + response time.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="uptime_monitor")
async def check_all() -> Dict[str, Any]:
    sites = _load_sites()
    if not sites: return {"ok": True, "note": "No sites monitored. Add some with uptime.add_site."}
    results = []
    for s in sites:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                import time; start = time.time()
                resp = await c.get(s["url"], follow_redirects=True)
                elapsed = round((time.time() - start) * 1000)
                results.append({"url": s["url"], "name": s["name"], "status": "up" if resp.status_code < 500 else "degraded", "http_code": resp.status_code, "response_ms": elapsed})
        except Exception as e:
            results.append({"url": s["url"], "name": s["name"], "status": "down", "error": str(e)[:100]})
    up = sum(1 for r in results if r["status"] == "up")
    return {"ok": True, "total": len(results), "up": up, "down": len(results)-up, "results": results}
