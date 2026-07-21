# Phase 18: Competitor Change Tracker (REAL)
from __future__ import annotations
import hashlib, json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import httpx
from backend.tools import tool, RiskTier

_TRACK_PATH = Path("./storage/competitor_snapshots.json")

@tool(name="competitor.add", description="Add a competitor URL to track for changes.", parameters={"type":"object","properties":{"url":{"type":"string"},"name":{"type":"string","default":""}},"required":["url"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="competitor_tracker")
async def competitor_add(url: str, name: str = "") -> Dict[str, Any]:
    data = json.loads(_TRACK_PATH.read_text()) if _TRACK_PATH.exists() else {}
    data[url] = {"name": name or url, "last_hash": "", "last_checked": ""}
    _TRACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TRACK_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "tracking": url}

@tool(name="competitor.diff", description="Check all tracked competitors for website changes since last scan.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="competitor_tracker")
async def competitor_diff() -> Dict[str, Any]:
    data = json.loads(_TRACK_PATH.read_text()) if _TRACK_PATH.exists() else {}
    if not data: return {"ok": True, "note": "No competitors tracked."}
    changes = []
    for url, info in data.items():
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            current_hash = hashlib.md5(resp.text.encode()).hexdigest()
            if info.get("last_hash") and current_hash != info["last_hash"]:
                changes.append({"url": url, "name": info["name"], "changed": True, "checked_at": datetime.utcnow().isoformat()})
            info["last_hash"] = current_hash
            info["last_checked"] = datetime.utcnow().isoformat()
        except Exception as e:
            changes.append({"url": url, "error": str(e)[:100]})
    _TRACK_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "checked": len(data), "changed": len([c for c in changes if c.get("changed")]), "results": changes}
