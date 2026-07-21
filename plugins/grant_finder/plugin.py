# JARVIS OMEGA - Grant Finder (Phase 16)
from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, List
from backend.tools import tool, RiskTier
from backend import business_db

_MENA_GRANTS = [
    {"name":"Oasis500","country":"Jordan","amount_usd":30000,"type":"accelerator","url":"https://oasis500.com"},
    {"name":"Shoman Foundation Innovation Fund","country":"Jordan","amount_usd":50000,"type":"grant","url":"https://shoman.org"},
    {"name":"Arab Bank Startup Program","country":"Jordan","amount_usd":15000,"type":"grant","url":"https://arabbank.com"},
    {"name":"SPARK Startup Support","country":"Regional","amount_usd":25000,"type":"grant","url":"https://spark-online.org"},
    {"name":"MIT Enterprise Forum Arab Startup","country":"Regional","amount_usd":50000,"type":"competition","url":"https://mitenterpriseforum.org"},
    {"name":"World Bank MENA SME Support","country":"Regional","amount_usd":100000,"type":"grant","url":"https://worldbank.org/mena"},
    {"name":"USAID Jordan Economic Development","country":"Jordan","amount_usd":75000,"type":"grant","url":"https://usaid.gov/jordan"},
    {"name":"EU Jordan SME Fund","country":"Jordan","amount_usd":40000,"type":"grant","url":"https://europa.eu"},
    {"name":"Qatar Development Fund","country":"Regional","amount_usd":50000,"type":"grant","url":"https://qatarfund.qa"},
    {"name":"AGFund (Arab Gulf Programme)","country":"Regional","amount_usd":100000,"type":"grant","url":"https://agfund.org"},
]

@tool(name="grant.list_mena", description="List active MENA startup grants, accelerators, and competitions.", parameters={"type":"object","properties":{"country":{"type":"string","default":""},"type":{"type":"string","default":"","enum":["","grant","accelerator","competition"]}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="grant_finder")
async def list_mena(country: str = "", gtype: str = "") -> Dict[str, Any]:
    grants = _MENA_GRANTS
    if country: grants = [g for g in grants if country.lower() in g["country"].lower()]
    if gtype: grants = [g for g in grants if g["type"] == gtype]
    # Persist to DB
    for g in grants:
        try: business_db.execute("INSERT OR IGNORE INTO grant_applications (grant_name, organization, amount_usd, status, created_at) VALUES (?, ?, ?, 'found', ?)",
            (g["name"], g["url"], g["amount_usd"], datetime.utcnow().isoformat()))
        except: pass
    return {"ok": True, "count": len(grants), "grants": grants}

@tool(name="grant.write_application", description="Generate a grant application proposal in Arabic for a specific grant.", parameters={"type":"object","properties":{"grant_name":{"type":"string"},"business_description":{"type":"string"},"amount_requested_usd":{"type":"number"},"language":{"type":"string","default":"ar"}},"required":["grant_name","business_description"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="grant_finder")
async def write_application(grant_name: str, business_description: str, amount_requested_usd: float = 10000, language: str = "ar") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Grant: {grant_name}\nBusiness: {business_description}\nAmount: ${amount_requested_usd}",
            system_instructions=f"Write a professional grant application in {'Arabic' if language=='ar' else 'English'}. Include: executive summary, problem statement, solution, impact, budget breakdown, team. 1500 words. Markdown.",
            inject_memory=False)
        from pathlib import Path
        out = Path("./storage/grants"); out.mkdir(parents=True, exist_ok=True)
        path = out / f"application_{grant_name.lower().replace(' ','_')}.md"
        path.write_text(reply, encoding="utf-8")
        business_db.execute("UPDATE grant_applications SET status = 'proposal_written', proposal_path = ? WHERE grant_name = ?", (str(path), grant_name))
        return {"ok": True, "path": str(path), "chars": len(reply)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="grant.list_tracked", description="List all tracked grants + their status.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="grant_finder")
async def list_tracked() -> Dict[str, Any]:
    rows = business_db.rows_to_dicts(business_db.query("SELECT * FROM grant_applications ORDER BY id DESC"))
    return {"ok": True, "grants": rows}

PLUGIN_NAME = "grant_finder"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "MENA startup grants: list + auto-write applications in Arabic."
