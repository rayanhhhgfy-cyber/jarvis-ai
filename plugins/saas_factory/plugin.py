# ====================================================================
# JARVIS OMEGA - SaaS Factory (Phase 14)
# ====================================================================
"""
Generate complete SaaS apps (FastAPI backend + Next.js frontend) from a niche.

  saas.spec_from_niche    - LLM spec
  saas.generate_backend   - FastAPI + SQLAlchemy + Alembic
  saas.generate_frontend  - Next.js + Tailwind dashboard
  saas.add_stripe         - Stripe subscription tiers
  saas.deploy_one_shot    - Vercel (frontend) + free DB tier (Supabase)
  saas.list_projects
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db


_SAAS_DIR = Path("./storage/saas_projects")
_SAAS_DIR.mkdir(parents=True, exist_ok=True)


@tool(
    name="saas.spec_from_niche",
    description="Generate a SaaS app spec from a niche. Returns full JSON spec with features, pricing, data models.",
    parameters={
        "type": "object",
        "properties": {
            "niche": {"type": "string"},
            "target_user": {"type": "string", "default": ""},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["niche"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="saas_factory",
)
async def saas_spec_from_niche(niche: str, target_user: str = "", language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    sys_prompt = (
        f"You are a senior SaaS architect. Design a shippable SaaS for this niche in {'Arabic' if language == 'ar' else 'English'}. "
        "Output STRICT JSON: {"
        "\"name\": string, \"tagline\": string, \"target_user\": string, "
        "\"core_features\": [string], \"data_models\": [{\"name\": string, \"fields\": [{\"name\": string, \"type\": string}]}], "
        "\"api_endpoints\": [{\"method\": string, \"path\": string, \"description\": string}], "
        "\"pricing_tiers\": [{\"name\": string, \"price_usd_monthly\": number, \"features\": [string]}], "
        "\"frontend_pages\": [{\"name\": string, \"purpose\": string}]}"
    )
    try:
        reply = await llm_service.get_response(
            user_message=f"Niche: {niche}\nTarget user: {target_user or 'general'}",
            system_instructions=sys_prompt, inject_memory=False,
        )
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        spec = json.loads(text)
        # Persist
        pid = business_db.execute(
            "INSERT INTO saas_projects (name, niche, status, created_at) VALUES (?, ?, 'spec', ?)",
            (spec.get("name", "Untitled SaaS"), niche, datetime.utcnow().isoformat()),
        )
        return {"ok": True, "project_id": pid, "spec": spec}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="saas.generate_backend",
    description="Generate a FastAPI backend from a SaaS spec. Writes main.py + models + routes + requirements.txt.",
    parameters={
        "type": "object",
        "properties": {
            "spec": {"type": "object"},
            "project_id": {"type": "integer", "default": 0},
            "output_dir": {"type": "string", "default": ""},
        },
        "required": ["spec"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="saas_factory",
)
async def saas_generate_backend(spec: Dict[str, Any], project_id: int = 0, output_dir: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    name = spec.get("name", "UntitledSaaS")
    out_dir = Path(output_dir) if output_dir else _SAAS_DIR / name.lower().replace(" ", "_") / "backend"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        code = await llm_service.get_response(
            user_message=f"SaaS spec:\n{json.dumps(spec, indent=2)}",
            system_instructions=(
                "Generate a complete FastAPI backend in a single main.py file. Include: "
                "SQLAlchemy models, Pydantic schemas, all CRUD routes, JWT auth, CORS, lifespan. "
                "Use SQLite for dev. Output Python only — no markdown fences."
            ),
            inject_memory=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    (out_dir / "main.py").write_text(code, encoding="utf-8")
    (out_dir / "requirements.txt").write_text(
        "fastapi==0.115.0\nuvicorn==0.34.0\nsqlalchemy==2.0.0\npydantic==2.11.0\npython-jose==3.4.0\npasslib==1.7.4\n",
        encoding="utf-8",
    )
    if project_id:
        business_db.execute("UPDATE saas_projects SET repo_url = ?, status = 'backend_generated' WHERE id = ?",
                            (str(out_dir), project_id))
    return {"ok": True, "backend_dir": str(out_dir), "main_py_chars": len(code)}


@tool(
    name="saas.generate_frontend",
    description="Generate a Next.js frontend (dashboard + auth + landing) from a SaaS spec.",
    parameters={
        "type": "object",
        "properties": {
            "spec": {"type": "object"},
            "output_dir": {"type": "string", "default": ""},
        },
        "required": ["spec"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="saas_factory",
)
async def saas_generate_frontend(spec: Dict[str, Any], output_dir: str = "") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    name = spec.get("name", "UntitledSaaS")
    out_dir = Path(output_dir) if output_dir else _SAAS_DIR / name.lower().replace(" ", "_") / "frontend"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate a landing page using existing tool.
    from plugins.website.plugin import website_generate_landing_page
    landing = await website_generate_landing_page(
        product_name=name,
        tagline=spec.get("tagline", ""),
        description=", ".join(spec.get("core_features", [])),
        features=spec.get("core_features", [])[:5],
        pricing=[
            {"name": t.get("name"), "price": f"${t.get('price_usd_monthly', 0)}/mo",
             "features": t.get("features", [])}
            for t in spec.get("pricing_tiers", [])[:3]
        ],
        output_dir=str(out_dir / "landing"),
    )

    # Generate a minimal dashboard HTML.
    try:
        dashboard = await llm_service.get_response(
            user_message=f"SaaS spec:\n{json.dumps(spec)[:3000]}",
            system_instructions=(
                "Generate a single-file HTML dashboard for this SaaS using Tailwind CDN + Chart.js CDN. "
                "Include: sidebar nav, 3 sections (overview, settings, billing), mock charts. "
                "Output HTML only."
            ),
            inject_memory=False,
        )
        (out_dir / "dashboard.html").write_text(dashboard, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "frontend_dir": str(out_dir), "landing_path": landing.get("path")}


@tool(
    name="saas.add_stripe",
    description="Generate Stripe subscription integration code (3 tiers).",
    parameters={
        "type": "object",
        "properties": {
            "spec": {"type": "object"},
            "backend_dir": {"type": "string"},
        },
        "required": ["spec", "backend_dir"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="saas_factory",
)
async def saas_add_stripe(spec: Dict[str, Any], backend_dir: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        code = await llm_service.get_response(
            user_message=f"Pricing tiers:\n{json.dumps(spec.get('pricing_tiers', []))}",
            system_instructions=(
                "Generate a Stripe subscription module (stripe_routes.py) using FastAPI + stripe Python SDK. "
                "Include: create-checkout-session endpoint for 3 tiers, webhook handler, "
                "customer portal redirect. Output Python only."
            ),
            inject_memory=False,
        )
        out = Path(backend_dir) / "stripe_routes.py"
        out.write_text(code, encoding="utf-8")
        return {"ok": True, "path": str(out)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="saas.deploy_one_shot",
    description="Deploy a SaaS: backend via Vercel/Render free, frontend via Vercel. Generates deploy configs.",
    parameters={
        "type": "object",
        "properties": {
            "project_dir": {"type": "string"},
            "project_id": {"type": "integer", "default": 0},
        },
        "required": ["project_dir"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="saas_factory",
)
async def saas_deploy_one_shot(project_dir: str, project_id: int = 0) -> Dict[str, Any]:
    pdir = Path(project_dir)
    if not pdir.is_dir():
        return {"ok": False, "error": "project dir not found"}
    # Generate Vercel config for frontend.
    vercel_json = {
        "version": 2,
        "builds": [{"src": "frontend/**", "use": "@vercel/static"}],
        "routes": [{"src": "/(.*)", "dest": "/frontend/$1"}],
    }
    (pdir / "vercel.json").write_text(json.dumps(vercel_json, indent=2), encoding="utf-8")
    # Generate Procfile for Render free backend.
    (pdir / "Procfile").write_text("web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT", encoding="utf-8")
    # Generate render.yaml
    render_yaml = """services:
  - type: web
    name: jarvis-saas
    env: python
    buildCommand: pip install -r backend/requirements.txt
    startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
    plan: free
"""
    (pdir / "render.yaml").write_text(render_yaml, encoding="utf-8")
    return {
        "ok": True, "project_dir": str(pdir),
        "next_steps": [
            "Frontend: deploy via `vercel --prod` from project_dir",
            "Backend: deploy via Render (https://render.com) — connect repo, free tier",
            "Database: free Supabase PostgreSQL (https://supabase.com)",
        ],
    }


@tool(
    name="saas.list_projects",
    description="List all SaaS projects.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="saas_factory",
)
async def saas_list_projects() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query(
        "SELECT * FROM saas_projects ORDER BY id DESC LIMIT 50",
    ))
    return {"ok": True, "count": len(rows), "projects": rows}


PLUGIN_NAME = "saas_factory"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "SaaS factory: spec → FastAPI + Next.js → Stripe → deploy (Vercel + Render + Supabase free)."
