# JARVIS OMEGA - Email Marketing (Phase 16)
from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="email.sequence_create", description="Create an email sequence (welcome/abandoned cart/win-back/upsell).", parameters={"type":"object","properties":{"name":{"type":"string"},"trigger_event":{"type":"string","enum":["signup","purchase","abandoned_cart","winback","manual"]},"steps":{"type":"array","items":{"type":"object"},"default":[],"description":"[{subject, body_template, delay_hours}]"}},"required":["name","trigger_event"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="email_marketing")
async def sequence_create(name: str, trigger_event: str = "signup", steps: Optional[List[Dict]] = None) -> Dict[str, Any]:
    steps = steps or []
    sid = business_db.execute("INSERT INTO email_sequences (name, trigger_event, steps_json, active, created_at) VALUES (?, ?, ?, 1, ?)",
        (name, trigger_event, json.dumps(steps), datetime.utcnow().isoformat()))
    return {"ok": True, "sequence_id": sid, "name": name, "step_count": len(steps)}

@tool(name="email.sequence_enroll", description="Enroll a contact into an email sequence.", parameters={"type":"object","properties":{"sequence_id":{"type":"integer"},"contact_email":{"type":"string"}},"required":["sequence_id","contact_email"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="email_marketing")
async def sequence_enroll(sequence_id: int, contact_email: str) -> Dict[str, Any]:
    eid = business_db.execute("INSERT INTO email_sequence_enrollments (sequence_id, contact_email, current_step, enrolled_at, next_send_at) VALUES (?, ?, 0, ?, ?)",
        (sequence_id, contact_email, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    return {"ok": True, "enrollment_id": eid}

@tool(name="email.sequence_process", description="Process pending sequence sends. Call this from a background job.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="email_marketing")
async def sequence_process() -> Dict[str, Any]:
    from plugins.communication.plugin import email_send
    pending = business_db.rows_to_dicts(business_db.query(
        "SELECT e.id, e.sequence_id, e.contact_email, e.current_step, e.next_send_at, s.steps_json FROM email_sequence_enrollments e JOIN email_sequences s ON e.sequence_id = s.id WHERE e.next_send_at <= ? AND s.active = 1",
        (datetime.utcnow().isoformat(),)))
    sent = 0
    for p in pending:
        steps = json.loads(p["steps_json"] or "[]")
        step_idx = p["current_step"]
        if step_idx >= len(steps): continue
        step = steps[step_idx]
        try:
            r = await email_send(to=p["contact_email"], subject=step.get("subject",""), body=step.get("body_template",""))
            if r.get("ok"):
                next_step = step_idx + 1
                next_send = (datetime.utcnow() + timedelta(hours=steps[next_step].get("delay_hours",24) if next_step < len(steps) else 9999)).isoformat() if next_step < len(steps) else None
                business_db.execute("UPDATE email_sequence_enrollments SET current_step = ?, next_send_at = ? WHERE id = ?",
                    (next_step, next_send, p["id"]))
                sent += 1
        except Exception: pass
    return {"ok": True, "sent": sent, "pending": len(pending)}

@tool(name="email.welcome_sequence", description="Auto-generate a 5-step Arabic welcome email sequence.", parameters={"type":"object","properties":{"business_name":{"type":"string"}},"required":["business_name"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="email_marketing")
async def welcome_sequence(business_name: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Business: {business_name}",
            system_instructions='Generate a 5-step Arabic welcome email sequence. Each step: subject + body. Steps: (1) welcome hour=0, (2) value hour=24, (3) story hour=72, (4) offer hour=120, (5) check-in hour=168. Output STRICT JSON: {"steps":[{"subject":string,"body_template":string,"delay_hours":int}]}',
            inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        steps = json.loads(text).get("steps",[])
        seq = await sequence_create(name=f"Welcome - {business_name}", trigger_event="signup", steps=steps)
        return {"ok": True, "sequence_id": seq.get("sequence_id"), "steps": len(steps)}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "email_marketing"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Email sequences: welcome, abandoned cart, win-back, upsell. Arabic templates. Background processing."
