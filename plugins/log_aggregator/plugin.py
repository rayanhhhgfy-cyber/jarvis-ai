# Phase 18: Log Aggregator (REAL)
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="logs.search", description="Search across all backend log files for a keyword.", parameters={"type":"object","properties":{"query":{"type":"string"},"level":{"type":"string","default":"","enum":["","error","warning","info"]}},"required":["query"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="log_aggregator")
async def search_logs(query: str, level: str = "") -> Dict[str, Any]:
    results = []
    for log_file in Path("./logs").rglob("*.log") if Path("./logs").exists() else []:
        try:
            for i, line in enumerate(log_file.read_text(encoding="utf-8", errors="ignore").splitlines()):
                if query.lower() in line.lower():
                    if level and level not in line.lower(): continue
                    results.append({"file": str(log_file), "line": i+1, "text": line[:200]})
                    if len(results) >= 50: break
        except: continue
    return {"ok": True, "query": query, "matches": len(results), "results": results[:20]}
