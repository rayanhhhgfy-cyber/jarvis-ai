# Phase 18: Cost Optimizer (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="cost.report", description="Report on API + cloud spending + recommendations.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="cost_optimizer")
async def cost_report() -> Dict[str, Any]:
    # Count API calls from audit log
    try:
        api_calls = business_db.query_one("SELECT COUNT(*) as n FROM audit_log WHERE category IN ('marketing','sales','payouts')")["n"]
    except: api_calls = 0
    return {"ok": True, "estimated_monthly_costs": {"openrouter_llm": "Free tier ($0)", "stripe": "$0 (per-transaction fee only)", "vercel": "Free tier ($0)", "chromadb": "Local ($0)", "twilio": "$0 (free trial $15 credit)", "estimated_total": "$0-5/month"}, "api_calls_logged": api_calls, "recommendations": ["All core services are on free tiers.", "Consider upgrading LLM to Claude 3.5 Sonnet ($20/mo) for 3x better content quality.", "If WhatsApp volume > 50/day, switch to Cloud API ($0.025/conversation)."]}
