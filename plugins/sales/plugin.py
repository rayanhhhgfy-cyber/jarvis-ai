# ====================================================================
# JARVIS OMEGA - Sales Plugin (Phase 11)
# ====================================================================
"""
CRM, lead generation, pitch decks, proposals, cold outreach.

All artifacts are written to disk under ``./storage/sales/`` and indexed
in the business DB (clients, contacts, deals tables).

Tools:
  sales.add_client / add_contact / list_clients
  sales.create_deal / update_deal_stage / pipeline
  sales.find_leads        - search public directories for businesses in a niche
  sales.create_pitch_deck - HTML deck (reveal.js via CDN)
  sales.write_proposal    - markdown -> PDF
  sales.write_cold_email  - LLM-personalized outreach
  sales.follow_up_sequence- generate 5-touch follow-up emails
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from shared.logger import get_logger

log = get_logger("sales")

_SALES_DIR = Path("./storage/sales")
_SALES_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------
# CRM
# --------------------------------------------------------------------

@tool(
    name="sales.add_client",
    description="Add a client (or prospect) to the CRM.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "niche": {"type": "string", "default": ""},
            "website": {"type": "string", "default": ""},
            "email": {"type": "string", "default": ""},
            "status": {"type": "string", "enum": ["prospect", "active", "churned"], "default": "prospect"},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_add_client(
    name: str, niche: str = "", website: str = "", email: str = "",
    status: str = "prospect", notes: str = "",
) -> Dict[str, Any]:
    cid = business_db.execute(
        """INSERT INTO clients (name, niche, website, email, status, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, niche, website, email, status, notes,
         datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )
    business_db.audit("add_client", "sales", target=name, details={"client_id": cid})
    return {"ok": True, "client_id": cid, "name": name}


@tool(
    name="sales.add_contact",
    description="Add a contact person to a client.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer"},
            "name": {"type": "string"},
            "role": {"type": "string", "default": ""},
            "email": {"type": "string", "default": ""},
            "phone": {"type": "string", "default": ""},
            "linkedin": {"type": "string", "default": ""},
        },
        "required": ["client_id", "name"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_add_contact(
    client_id: int, name: str, role: str = "", email: str = "",
    phone: str = "", linkedin: str = "",
) -> Dict[str, Any]:
    cid = business_db.execute(
        """INSERT INTO contacts (client_id, name, role, email, phone, linkedin, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (client_id, name, role, email, phone, linkedin, datetime.utcnow().isoformat()),
    )
    return {"ok": True, "contact_id": cid}


@tool(
    name="sales.list_clients",
    description="List all clients/prospects, optionally filtered by status.",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 100},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="sales",
)
async def sales_list_clients(status: str = "", limit: int = 100) -> Dict[str, Any]:
    sql = "SELECT * FROM clients"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "clients": rows}


# --------------------------------------------------------------------
# Deals / pipeline
# --------------------------------------------------------------------

@tool(
    name="sales.create_deal",
    description="Create a deal in the pipeline.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer"},
            "title": {"type": "string"},
            "value": {"type": "number", "default": 0},
            "currency": {"type": "string", "default": "USD"},
            "stage": {"type": "string", "default": "lead",
                      "enum": ["lead", "qualified", "pitched", "negotiated", "won", "lost"]},
            "probability": {"type": "integer", "default": 10},
            "expected_close": {"type": "string", "default": ""},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["client_id", "title"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_create_deal(
    client_id: int, title: str, value: float = 0, currency: str = "USD",
    stage: str = "lead", probability: int = 10,
    expected_close: str = "", notes: str = "",
) -> Dict[str, Any]:
    did = business_db.execute(
        """INSERT INTO deals (client_id, title, value, currency, stage, probability,
                              expected_close, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, title, value, currency, stage, probability,
         expected_close or None, notes, datetime.utcnow().isoformat(),
         datetime.utcnow().isoformat()),
    )
    return {"ok": True, "deal_id": did, "title": title}


@tool(
    name="sales.update_deal_stage",
    description="Move a deal to a different pipeline stage.",
    parameters={
        "type": "object",
        "properties": {
            "deal_id": {"type": "integer"},
            "stage": {"type": "string", "enum": ["lead", "qualified", "pitched", "negotiated", "won", "lost"]},
            "probability": {"type": "integer", "default": -1, "description": "Optional new probability 0-100. -1 = unchanged."},
        },
        "required": ["deal_id", "stage"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_update_deal_stage(deal_id: int, stage: str, probability: int = -1) -> Dict[str, Any]:
    if probability >= 0:
        business_db.execute(
            "UPDATE deals SET stage = ?, probability = ?, updated_at = ? WHERE id = ?",
            (stage, probability, datetime.utcnow().isoformat(), deal_id),
        )
    else:
        business_db.execute(
            "UPDATE deals SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, datetime.utcnow().isoformat(), deal_id),
        )
    business_db.audit("update_deal", "sales", target=str(deal_id), details={"stage": stage})
    return {"ok": True, "deal_id": deal_id, "stage": stage}


@tool(
    name="sales.pipeline",
    description="Show the current sales pipeline grouped by stage with total value.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="sales",
)
async def sales_pipeline() -> Dict[str, Any]:
    rows = business_db.query(
        "SELECT stage, COUNT(*) as n, COALESCE(SUM(value), 0) as total FROM deals GROUP BY stage"
    )
    out = {r["stage"]: {"count": r["n"], "value": r["total"]} for r in rows}
    return {"ok": True, "pipeline": out}


# --------------------------------------------------------------------
# Lead generation (free public sources)
# --------------------------------------------------------------------

@tool(
    name="sales.find_leads",
    description="Find businesses in a niche. Uses the free OpenStreetMap Overpass API to find local businesses by category.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string", "description": "e.g. 'restaurant', 'salon', 'plumber', 'lawyer'"},
            "location": {"type": "string", "description": "City / region, e.g. 'Brooklyn, NY'"},
            "limit": {"type": "integer", "default": 25},
        },
        "required": ["niche", "location"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="sales",
)
async def sales_find_leads(niche: str, location: str, limit: int = 25) -> Dict[str, Any]:
    # Step 1: geocode the location.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            geo = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": location, "format": "json", "limit": 1},
                headers={"User-Agent": "JARVIS-OMEGA/1.0"},
            )
        geo_data = geo.json()
        if not geo_data:
            return {"ok": False, "error": f"could not geocode '{location}'"}
        lat = float(geo_data[0]["lat"])
        lon = float(geo_data[0]["lon"])
        # Search a 25km box
        async with httpx.AsyncClient(timeout=30) as client:
            q = (
                f"[out:json][timeout:25];"
                f"node(around:25000,{lat},{lon})[\"amenity\"=\"{niche}\"];"
                f"out center {limit};"
            )
            ov = await client.post("https://overpass-api.de/api/interpreter", data={"data": q})
        leads = []
        for el in ov.json().get("elements", [])[:limit]:
            tags = el.get("tags", {})
            if not tags.get("name"):
                continue
            leads.append({
                "name": tags.get("name"),
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "website": tags.get("website", tags.get("contact:website", "")),
                "email": tags.get("email", tags.get("contact:email", "")),
                "address": tags.get("addr:housenumber", "") + " " + tags.get("addr:street", ""),
                "city": tags.get("addr:city", ""),
                "latitude": el.get("lat"),
                "longitude": el.get("lon"),
            })
        return {"ok": True, "niche": niche, "location": location, "count": len(leads), "leads": leads}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Pitch deck + proposal generators
# --------------------------------------------------------------------

_PITCH_DECK_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.revealjs.org/4.6.1/reset.css">
<link rel="stylesheet" href="https://cdn.revealjs.org/4.6.1/reveal.css">
<link rel="stylesheet" href="https://cdn.revealjs.org/4.6.1/theme/{theme}.css" id="theme">
</head>
<body>
<div class="reveal"><div class="slides">
{slides_html}
</div></div>
<script src="https://cdn.revealjs.org/4.6.1/reveal.js"></script>
<script>Reveal.initialize({{ hash: true, slideNumber: true }});</script>
</body>
</html>"""


@tool(
    name="sales.create_pitch_deck",
    description="Generate a self-contained HTML pitch deck (reveal.js via CDN). Takes a brief and produces 8-12 slides.",
    parameters={
        "type": "object",
        "properties": {
            "brief": {"type": "string", "description": "Product/service brief. What you sell, to whom, why it matters."},
            "client_name": {"type": "string", "default": "Sir"},
            "theme": {"type": "string", "default": "black", "enum": ["black", "white", "league", "sky", "beige", "simple", "serif", "blood", "moon", "night"]},
            "filename": {"type": "string", "default": ""},
        },
        "required": ["brief"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_create_pitch_deck(
    brief: str, client_name: str = "Sir", theme: str = "black", filename: str = "",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        "You are a senior pitch-deck writer. Output STRICT JSON: "
        "{\"slides\": [{\"title\": string, \"bullets\": [string, ...]}, ...]}. "
        "Create 8-12 slides following the Sequoia/YC structure: "
        "Problem, Solution, Market, Product, Traction, Business Model, "
        "Go-to-Market, Competition, Team, Financials, Ask. "
        "Each bullet max 12 words. No markdown fences."
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Client: {client_name}\nBrief: {brief}",
            system_instructions=sys_prompt,
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": f"LLM failed: {e}"}

    try:
        parsed = _parse_json(reply)
    except Exception as e:
        return {"ok": False, "error": f"LLM JSON parse failed: {e}", "raw": reply[:300]}

    slides_html_parts = []
    for s in parsed.get("slides", []):
        bullets = "".join(f"<li>{b}</li>" for b in s.get("bullets", []))
        slides_html_parts.append(
            f"<section><h2>{s.get('title','')}</h2><ul>{bullets}</ul></section>"
        )
    fname = filename or f"pitch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
    path = _SALES_DIR / fname
    html = _PITCH_DECK_TEMPLATE.format(
        title=f"Pitch - {client_name}",
        theme=theme,
        slides_html="\n".join(slides_html_parts),
    )
    path.write_text(html, encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "slides": len(parsed.get("slides", [])),
        "client": client_name,
    }


@tool(
    name="sales.write_proposal",
    description="Generate a markdown proposal document for a client.",
    parameters={
        "type": "object",
        "properties": {
            "client_name": {"type": "string"},
            "brief": {"type": "string", "description": "What you're proposing to do for them."},
            "price": {"type": "number", "default": 0},
            "timeline_weeks": {"type": "integer", "default": 4},
            "filename": {"type": "string", "default": ""},
        },
        "required": ["client_name", "brief"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_write_proposal(
    client_name: str, brief: str, price: float = 0, timeline_weeks: int = 4,
    filename: str = "",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=(
                f"Client: {client_name}\n"
                f"Project: {brief}\n"
                f"Price: ${price}\n"
                f"Timeline: {timeline_weeks} weeks\n"
                "Generate a full professional proposal in Markdown. Include sections: "
                "Executive Summary, Goals, Scope of Work, Deliverables, Timeline, "
                "Pricing, Terms, Next Steps."
            ),
            system_instructions="You are a senior proposal writer. Output only Markdown.",
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    fname = filename or f"proposal_{client_name.lower().replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d')}.md"
    path = _SALES_DIR / fname
    path.write_text(reply, encoding="utf-8")
    return {"ok": True, "path": str(path), "chars": len(reply)}


@tool(
    name="sales.write_cold_email",
    description="Generate a personalized cold-outreach email for a prospect.",
    parameters={
        "type": "object",
        "properties": {
            "prospect_name": {"type": "string"},
            "prospect_company": {"type": "string"},
            "service_offered": {"type": "string"},
            "tone": {"type": "string", "default": "consultative"},
        },
        "required": ["prospect_name", "prospect_company", "service_offered"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_write_cold_email(
    prospect_name: str, prospect_company: str, service_offered: str,
    tone: str = "consultative",
) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=(
                f"Prospect: {prospect_name} at {prospect_company}\n"
                f"Service: {service_offered}\n"
                f"Tone: {tone}\n"
                "Write a 4-sentence cold email. No fluff. End with a clear CTA."
                "Output STRICT JSON: {\"subject\": string, \"body\": string}. No fences."
            ),
            system_instructions="You are a senior SDR. Output JSON only.",
            inject_memory=False,
        )
        parsed = _parse_json(reply)
        return {"ok": True, "subject": parsed.get("subject", ""), "body": parsed.get("body", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="sales.follow_up_sequence",
    description="Generate a 5-touch follow-up email sequence for a cold lead.",
    parameters={
        "type": "object",
        "properties": {
            "prospect_name": {"type": "string"},
            "service_offered": {"type": "string"},
        },
        "required": ["prospect_name", "service_offered"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="sales",
)
async def sales_follow_up_sequence(prospect_name: str, service_offered: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=(
                f"Prospect: {prospect_name}\nService: {service_offered}\n"
                "Generate a 5-touch follow-up sequence. "
                "Day 1 (initial value), Day 3 (case study), Day 7 (quick question), "
                "Day 12 (different angle), Day 18 (breakup). "
                "Output STRICT JSON: {\"sequence\": [{\"day\": int, \"subject\": string, \"body\": string}]}."
            ),
            system_instructions="You are a senior SDR. Output JSON only.",
            inject_memory=False,
        )
        parsed = _parse_json(reply)
        return {"ok": True, "sequence": parsed.get("sequence", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Helper - JSON salvage
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


PLUGIN_NAME = "sales"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "CRM (clients/contacts/deals), lead gen via OpenStreetMap, pitch decks (reveal.js), proposals, cold emails."
