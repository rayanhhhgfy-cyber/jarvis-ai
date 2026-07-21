# ====================================================================
# JARVIS OMEGA - Auto-Freelancer (Phase 14)
# ====================================================================
"""
Find + bid on + deliver freelance jobs on Upwork + Fiverr.

⚠️ ToS GUARD: Upwork explicitly bans bots. JARVIS ASSISTS only — opens the
browser pre-filled; Sir clicks submit. No auto-submit.

  freelance.scan_upwork        - scrape RSS for matching jobs
  freelance.bid_write          - LLM writes personalized proposal
  freelance.bid_submit_assisted - open browser pre-filled (Sir clicks submit)
  freelance.deliver_work       - LLM does the work + packages deliverable
  freelance.fiverr_gig_create  - LLM generates gig descriptions
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db

_FREELANCE_DIR = Path("./storage/freelance")
_FREELANCE_DIR.mkdir(parents=True, exist_ok=True)


@tool(
    name="freelance.scan_upwork",
    description="Search Upwork RSS feed for jobs matching JARVIS's skills.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "default": "python developer"},
            "limit": {"type": "integer", "default": 15},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="freelancer",
)
async def freelance_scan_upwork(query: str = "python developer", limit: int = 15) -> Dict[str, Any]:
    try:
        # Upwork has RSS feeds for search results.
        encoded = urllib.parse.quote(query)
        url = f"https://www.upwork.com/ab/feed/jobs/rss?q={encoded}&sort=recency"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        # Parse RSS XML.
        import re
        items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
        jobs = []
        for item in items[:limit]:
            title_m = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
            link_m = re.search(r"<link>(.*?)</link>", item, re.DOTALL)
            desc_m = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", item, re.DOTALL)
            pub_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
            jobs.append({
                "title": (title_m.group(1) if title_m else "").strip(),
                "url": (link_m.group(1) if link_m else "").strip(),
                "description": (desc_m.group(1) if desc_m else "")[:500].strip(),
                "published": (pub_m.group(1) if pub_m else "").strip(),
            })
        return {"ok": True, "query": query, "count": len(jobs), "jobs": jobs}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="freelance.bid_write",
    description="Generate a personalized proposal for an Upwork job.",
    parameters={
        "type": "object",
        "properties": {
            "job_title": {"type": "string"},
            "job_description": {"type": "string"},
            "your_skills": {"type": "string", "default": "Python, FastAPI, automation, AI integration"},
            "language": {"type": "string", "default": "en"},
            "rate_usd": {"type": "number", "default": 35},
        },
        "required": ["job_title", "job_description"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="freelancer",
)
async def freelance_bid_write(
    job_title: str, job_description: str,
    your_skills: str = "Python, FastAPI, automation, AI integration",
    language: str = "en", rate_usd: float = 35,
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=(
                f"Job: {job_title}\nDescription: {job_description}\n"
                f"My skills: {your_skills}\nRate: ${rate_usd}/hr"
            ),
            system_instructions=(
                f"Write a personalized Upwork proposal in {'Arabic' if language == 'ar' else 'English'}. "
                "Be concise (under 150 words). Lead with the specific problem they mentioned. "
                "Reference one detail from the job description. End with a clear next step."
            ),
            inject_memory=False,
        )
        return {"ok": True, "proposal": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="freelance.bid_submit_assisted",
    description="Open the browser pre-filled with a proposal. Sir clicks submit manually (Upwork ToS safe).",
    parameters={
        "type": "object",
        "properties": {
            "job_url": {"type": "string"},
            "proposal_text": {"type": "string"},
        },
        "required": ["job_url"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="freelancer",
)
async def freelance_bid_submit_assisted(job_url: str, proposal_text: str = "") -> Dict[str, Any]:
    try:
        webbrowser.open(job_url)
    except Exception as e:
        return {"ok": False, "error": f"couldn't open browser: {e}"}
    return {
        "ok": True, "job_url": job_url,
        "proposal_in_clipboard": False,
        "instructions": "Browser opened to the job page. Copy the proposal text below and paste into the bid form.",
        "proposal_text": proposal_text,
        "tos_warning": "Upwork ToS prohibits automated submission. Sir must click submit manually.",
    }


@tool(
    name="freelance.deliver_work",
    description="Generate the deliverable for a freelance job.",
    parameters={
        "type": "object",
        "properties": {
            "job_title": {"type": "string"},
            "job_description": {"type": "string"},
            "deliverable_type": {"type": "string", "enum": ["code", "article", "research", "design_spec"], "default": "code"},
        },
        "required": ["job_title", "job_description"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="freelancer",
)
async def freelance_deliver_work(job_title: str, job_description: str, deliverable_type: str = "code") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    instructions = {
        "code": "Generate production-ready code in a single file. Include docstrings + tests.",
        "article": "Write a long-form article (1500+ words). Markdown. Include H2/H3 sections.",
        "research": "Output a research report with executive summary, findings (with sources), recommendations.",
        "design_spec": "Output a design spec with user flows, wireframe descriptions, color palette, typography.",
    }[deliverable_type]
    try:
        work = await llm_service.get_response(
            user_message=f"Job: {job_title}\nDescription: {job_description}",
            system_instructions=instructions,
            inject_memory=False,
        )
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        ext = {"code": ".py", "article": ".md", "research": ".md", "design_spec": ".md"}[deliverable_type]
        safe = "".join(c for c in job_title.lower() if c.isalnum() or c == "_")[:50]
        path = _FREELANCE_DIR / f"deliverable_{safe}_{stamp}{ext}"
        path.write_text(work, encoding="utf-8")
        return {"ok": True, "deliverable_path": str(path), "chars": len(work), "type": deliverable_type}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="freelance.fiverr_gig_create",
    description="Generate Fiverr gig descriptions for JARVIS's specialties.",
    parameters={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "default": "Python automation"},
            "language": {"type": "string", "default": "en"},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="freelancer",
)
async def freelance_fiverr_gig_create(skill: str = "Python automation", language: str = "en") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Skill: {skill}",
            system_instructions=(
                f"Generate a Fiverr gig listing in {'Arabic' if language == 'ar' else 'English'}. "
                "Output STRICT JSON: {\"title\": string, \"description\": string, "
                "\"packages\": [{\"name\": \"Basic\", \"price_usd\": number, \"delivery_days\": integer, \"features\": [string]}], "
                "\"tags\": [string]}"
            ),
            inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        return {"ok": True, "skill": skill, "gig": parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "freelancer"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Auto-freelancer: scan Upwork, write proposals, assist submission (ToS-safe), deliver work, Fiverr gigs."
