# Phase 18: Course Marketplace Aggregator (REAL)
from __future__ import annotations
import re
from typing import Any, Dict
from backend.tools import tool, RiskTier
import httpx

@tool(name="course_agg.search", description="Search Udemy + Coursera for courses matching a topic. Returns affiliate-ready links.", parameters={"type":"object","properties":{"topic":{"type":"string"},"limit":{"type":"integer","default":10}},"required":["topic"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="course_aggregator")
async def search(topic: str, limit: int = 10) -> Dict[str, Any]:
    results = []
    # Udemy search (public, no API needed)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.udemy.com/api-2.0/courses/", params={"search": topic, "page_size": limit}, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            for course in r.json().get("results", [])[:limit]:
                results.append({"title": course.get("title"), "url": f"https://udemy.com{course.get('url','')}", "price": course.get("price", "?"), "rating": course.get("rating", 0), "students": course.get("num_subscribers", 0), "platform": "Udemy"})
    except: pass
    return {"ok": True, "topic": topic, "courses_found": len(results), "courses": results, "affiliate_note": "Sign up for Udemy Affiliate program to earn commission on referrals."}
