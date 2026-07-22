# Phase 19: Review Analysis Engine (REAL)
from __future__ import annotations
import json
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="review.analyze", description="Analyze customer reviews for sentiment + common themes + actionable insights.", parameters={"type":"object","properties":{"reviews":{"type":"array","items":{"type":"string"},"description":"List of review texts"}},"required":["reviews"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="review_analysis")
async def analyze(reviews: list) -> Dict[str, Any]:
    if not reviews: return {"ok": False, "error": "No reviews provided"}
    from backend.services.llm_service import llm_service
    from plugins.support.plugin import support_sentiment_analyze
    # Sentiment per review
    sentiments = []
    for r in reviews[:50]:
        s = await support_sentiment_analyze(text=r)
        sentiments.append(s.get("sentiment","neutral"))
    pos = sentiments.count("positive"); neg = sentiments.count("negative"); neu = sentiments.count("neutral")
    # LLM theme analysis
    try:
        reply = await llm_service.get_response(user_message="Reviews:\n" + "\n".join(reviews[:20]), system_instructions='Analyze these reviews. Output STRICT JSON: {themes:[{theme:string,sentiment:positive|negative,count:int}], top_complaints:[string], top_praises:[string], action_items:[string]}', inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        themes = json.loads(text)
    except: themes = {}
    return {"ok": True, "total_reviews": len(reviews), "positive_pct": round(pos/len(sentiments)*100), "negative_pct": round(neg/len(sentiments)*100), "neutral_pct": round(neu/len(sentiments)*100), **themes}

PLUGIN_NAME = "review_analysis"; PLUGIN_VERSION = "1.0.0"
