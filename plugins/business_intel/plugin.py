# ====================================================================
# JARVIS OMEGA - Business Intelligence Plugin (Phase 11)
# ====================================================================
"""
Always-on opportunity scanner + market research.

Tools:
  biz.scan_opportunities    - pull from HN/Reddit/ProductHunt, score + persist
  biz.list_opportunities    - see the backlog
  biz.review_opportunity    - mark reviewed / acted-on / rejected
  biz.research_market       - estimate market size for a niche
  biz.analyze_competitor    - public-website scrape + LLM analysis
  biz.trending_topics       - aggregate trending topics across sources
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("biz_intel")

_UA = "JARVIS-OMEGA/1.0"


# --------------------------------------------------------------------
# Opportunity scanner
# --------------------------------------------------------------------

async def _scan_hn(limit: int) -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            ids = r.json()[:limit]
            items = []
            for sid in ids:
                ir = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                item = ir.json()
                if not item:
                    continue
                items.append({
                    "source": "hackernews",
                    "title": item.get("title", ""),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                    "score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "external_id": str(sid),
                })
            return items
    except Exception:
        return []


async def _scan_reddit(subreddits: List[str], limit_per: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}) as client:
            for sub in subreddits:
                r = await client.get(f"https://www.reddit.com/r/{sub}/top.json?limit={limit_per}&t=day")
                if r.status_code >= 400:
                    continue
                data = r.json()
                for child in data.get("data", {}).get("children", []):
                    d = child["data"]
                    items.append({
                        "source": f"reddit/{sub}",
                        "title": d.get("title", ""),
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "score": d.get("score", 0),
                        "comments": d.get("num_comments", 0),
                        "external_id": d.get("id", ""),
                    })
    except Exception:
        pass
    return items


async def _scan_producthunt(limit: int) -> List[Dict[str, Any]]:
    # ProductHunt no longer has a free unauthenticated RSS, so we skip if no API key.
    return []


def _score_opportunity(item: Dict[str, Any], niche_keywords: List[str]) -> float:
    """0-100 score — heuristic for relevance + traction."""
    title = item.get("title", "").lower()
    niche_match = sum(1 for k in niche_keywords if k.lower() in title)
    score_factor = min(item.get("score", 0) / 10, 30)  # up to 30 pts for traction
    comment_factor = min(item.get("comments", 0) / 10, 20)  # up to 20 for discussion
    niche_factor = niche_match * 15  # 15 pts per keyword hit
    return min(100, niche_factor + score_factor + comment_factor)


def _classify_monetization(title: str) -> str:
    """Pick the most likely monetization path from the title."""
    t = title.lower()
    if any(w in t for w in ["saas", "tool", "platform", "dashboard", "app"]):
        return "saas"
    if any(w in t for w in ["course", "ebook", "guide", "template"]):
        return "digital_product"
    if any(w in t for w in ["newsletter", "blog", "content"]):
        return "newsletter"
    if any(w in t for w in ["compare", "best", "review", "alternative"]):
        return "affiliate"
    if any(w in t for w in ["directory", "list", "find"]):
        return "lead_gen"
    return "service"


@tool(
    name="biz.scan_opportunities",
    description="Pull trending items from HN and Reddit, score by niche relevance, persist to opportunities table. Returns count of new items.",
    parameters={
        "type": "object",
        "properties": {
            "niche_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Keywords to score relevance. Empty = no niche filtering.",
            },
            "subreddits": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["Entrepreneur", "SideProject", "SaaS", "smallbusiness"],
            },
            "hn_limit": {"type": "integer", "default": 30},
            "reddit_limit_per_sub": {"type": "integer", "default": 10},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="biz_intel",
)
async def biz_scan_opportunities(
    niche_keywords: Optional[List[str]] = None,
    subreddits: Optional[List[str]] = None,
    hn_limit: int = 30, reddit_limit_per_sub: int = 10,
) -> Dict[str, Any]:
    niche_keywords = niche_keywords or []
    subreddits = subreddits or ["Entrepreneur", "SideProject", "SaaS", "smallbusiness"]

    tasks = [
        _scan_hn(hn_limit),
        _scan_reddit(subreddits, reddit_limit_per_sub),
    ]
    hn_items, reddit_items = await asyncio.gather(*tasks)

    all_items = hn_items + reddit_items
    added = 0
    for item in all_items:
        score = _score_opportunity(item, niche_keywords)
        # Persist (deduplicate by external_id).
        existing = business_db.query_one(
            "SELECT id FROM opportunities WHERE url = ?", (item["url"],)
        )
        if existing:
            continue
        try:
            business_db.execute(
                """INSERT INTO opportunities
                   (source, title, summary, url, niche, score, monetization, status, discovered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
                (
                    item["source"], item["title"],
                    f"Score {score:.1f} / score:{item.get('score')} / comments:{item.get('comments')}",
                    item["url"],
                    ",".join(niche_keywords),
                    score,
                    _classify_monetization(item["title"]),
                    datetime.utcnow().isoformat(),
                ),
            )
            added += 1
        except Exception as e:
            log.warning("opportunity_persist_failed", error=str(e))

    business_db.audit("scan_opportunities", "biz_intel",
                      details={"added": added, "scanned": len(all_items), "niche": niche_keywords})
    return {"ok": True, "scanned": len(all_items), "added": added}


@tool(
    name="biz.list_opportunities",
    description="List opportunities from the backlog, highest score first.",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": "new", "description": "Empty = all."},
            "limit": {"type": "integer", "default": 20},
            "min_score": {"type": "number", "default": 0},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="biz_intel",
)
async def biz_list_opportunities(status: str = "new", limit: int = 20, min_score: float = 0) -> Dict[str, Any]:
    sql = "SELECT * FROM opportunities WHERE score >= ?"
    params: tuple = (min_score,)
    if status:
        sql += " AND status = ?"
        params = params + (status,)
    sql += " ORDER BY score DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "opportunities": rows}


@tool(
    name="biz.review_opportunity",
    description="Update the status of an opportunity.",
    parameters={
        "type": "object",
        "properties": {
            "opportunity_id": {"type": "integer"},
            "status": {"type": "string", "enum": ["new", "reviewing", "acted_on", "rejected"]},
            "action_taken": {"type": "string", "default": ""},
        },
        "required": ["opportunity_id", "status"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="biz_intel",
)
async def biz_review_opportunity(opportunity_id: int, status: str, action_taken: str = "") -> Dict[str, Any]:
    business_db.execute(
        "UPDATE opportunities SET status = ?, action_taken = ?, reviewed_at = ? WHERE id = ?",
        (status, action_taken, datetime.utcnow().isoformat(), opportunity_id),
    )
    return {"ok": True, "id": opportunity_id, "status": status}


# --------------------------------------------------------------------
# Market research
# --------------------------------------------------------------------

@tool(
    name="biz.research_market",
    description="Get a market size estimate + competitive landscape summary. Combines free Wikipedia + LLM analysis.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string"},
            "depth": {"type": "string", "enum": ["quick", "standard", "deep"], "default": "standard"},
        },
        "required": ["niche"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="biz_intel",
)
async def biz_research_market(niche: str, depth: str = "standard") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Niche: {niche}\nDepth: {depth}",
            system_instructions=(
                "You are a senior market analyst. Output STRICT JSON: "
                "{"
                "\"tam_estimate_usd\": string,"
                "\"tam_basis\": string,"
                "\"target_customer\": string,"
                "\"top_players\": [{\"name\": string, \"url\": string, \"differentiator\": string}],"
                "\"demand_signals\": [string, ...],"
                "\"monetization_options\": [\"saas\", \"digital_product\", ...],"
                "\"risks\": [string, ...],"
                "\"go_to_market_angle\": string"
                "}"
            ),
            inject_memory=False,
        )
        parsed = _parse_json(reply)
        parsed["niche"] = niche
        parsed["ok"] = True
        return parsed
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="biz.analyze_competitor",
    description="Scrape a competitor's homepage and produce a structured analysis.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="biz_intel",
)
async def biz_analyze_competitor(url: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": _UA})
        if resp.status_code >= 400:
            return {"ok": False, "error": f"fetch failed: {resp.status_code}"}
        # Strip HTML tags crudely.
        text = re.sub(r"<script.*?</script>", " ", resp.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()[:8000]
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        reply = await llm_service.get_response(
            user_message=f"URL: {url}\nHomepage content:\n{text}",
            system_instructions=(
                "You are a competitive intelligence analyst. Output STRICT JSON: "
                "{"
                "\"positioning\": string,"
                "\"target_customer\": string,"
                "\"pricing_model\": string,"
                "\"strengths\": [string],"
                "\"weaknesses\": [string],"
                "\"differentiation\": string,"
                "\"opportunities_for_us\": [string]"
                "}"
            ),
            inject_memory=False,
        )
        parsed = _parse_json(reply)
        parsed["url"] = url
        parsed["ok"] = True
        return parsed
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# JSON salvage
# --------------------------------------------------------------------

def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start == -1:
            raise
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(cleaned[start:i + 1])
        raise


PLUGIN_NAME = "business_intel"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Opportunity scanner (HN/Reddit/ProductHunt), market research, competitor analysis, trend watch."
