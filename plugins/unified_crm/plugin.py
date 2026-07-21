# JARVIS OMEGA - Unified CRM (Phase 16)
from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="crm.capture", description="Capture a lead from any channel into the unified CRM.", parameters={"type":"object","properties":{"name":{"type":"string"},"phone":{"type":"string","default":""},"email":{"type":"string","default":""},"instagram":{"type":"string","default":""},"source":{"type":"string","default":"manual"},"business_id":{"type":"integer","default":0},"notes":{"type":"string","default":""}},"required":["name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="unified_crm")
async def crm_capture(name: str, phone: str = "", email: str = "", instagram: str = "", source: str = "manual", business_id: int = 0, notes: str = "") -> Dict[str, Any]:
    lid = business_db.execute("INSERT INTO crm_leads (name, phone, email, instagram, source, business_id, score, status, notes, created_at) VALUES (?,?,?,?,?,?,0,'new',?,?)",
        (name, phone, email, instagram, source, business_id or None, notes, datetime.utcnow().isoformat()))
    return {"ok": True, "lead_id": lid, "name": name, "source": source}

@tool(name="crm.list_leads", description="List CRM leads. Filter by status.", parameters={"type":"object","properties":{"status":{"type":"string","default":""},"limit":{"type":"integer","default":50}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="unified_crm")
async def crm_list_leads(status: str = "", limit: int = 50) -> Dict[str, Any]:
    sql = "SELECT * FROM crm_leads"; params = ()
    if status: sql += " WHERE status = ?"; params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"; params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "leads": rows}

@tool(name="crm.score_lead", description="Score a lead 0-100 based on engagement signals.", parameters={"type":"object","properties":{"lead_id":{"type":"integer"}},"required":["lead_id"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="unified_crm")
async def crm_score_lead(lead_id: int) -> Dict[str, Any]:
    lead = business_db.query_one("SELECT * FROM crm_leads WHERE id = ?", (lead_id,))
    if not lead: return {"ok": False, "error": "lead not found"}
    score = 0
    if lead["phone"]: score += 25
    if lead["email"]: score += 20
    if lead["instagram"]: score += 15
    if lead["source"] in ("whatsapp","instagram"): score += 20
    if lead["notes"]: score += 10
    business_db.execute("UPDATE crm_leads SET score = ? WHERE id = ?", (score, lead_id))
    return {"ok": True, "lead_id": lead_id, "score": score, "verdict": "HOT" if score>=70 else "WARM" if score>=40 else "COLD"}

@tool(name="crm.update_status", description="Update a lead's status in the pipeline.", parameters={"type":"object","properties":{"lead_id":{"type":"integer"},"status":{"type":"string","enum":["new","contacted","qualified","pitched","won","lost"]}},"required":["lead_id","status"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="unified_crm")
async def crm_update_status(lead_id: int, status: str) -> Dict[str, Any]:
    business_db.execute("UPDATE crm_leads SET status = ? WHERE id = ?", (status, lead_id))
    return {"ok": True, "lead_id": lead_id, "status": status}

@tool(name="crm.pipeline_view", description="Show pipeline: how many leads at each stage.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="unified_crm")
async def crm_pipeline_view() -> Dict[str, Any]:
    rows = business_db.query("SELECT status, COUNT(*) as n FROM crm_leads GROUP BY status")
    return {"ok": True, "pipeline": {r["status"]: r["n"] for r in rows}}

PLUGIN_NAME = "unified_crm"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Unified CRM: omnichannel lead capture, scoring, pipeline view."
