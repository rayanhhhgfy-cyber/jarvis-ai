# JARVIS OMEGA - Arabic Legal Contract Review (Phase 16)
from __future__ import annotations
import json
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="legal_review.red_flag", description="Upload an Arabic contract and get risky clauses red-flagged. Returns severity + recommendation per finding.", parameters={"type":"object","properties":{"contract_text":{"type":"string"},"jurisdiction":{"type":"string","default":"Jordan"}},"required":["contract_text"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="legal_review")
async def red_flag(contract_text: str, jurisdiction: str = "Jordan") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Contract text:\n{contract_text[:8000]}\n\nJurisdiction: {jurisdiction}",
            system_instructions='You are a Jordanian contract lawyer. Red-flag every risky clause. Output STRICT JSON: {"findings":[{"severity":"high|medium|low","clause_quote":string,"issue":string,"recommendation":string,"legal_basis":string}],"overall_risk":"high|medium|low","summary":string}',
            inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        return {"ok": True, **parsed, "disclaimer": "Heuristic analysis. Have a licensed lawyer review before signing."}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="legal_review.compare_contracts", description="Compare two contract versions and show what changed.", parameters={"type":"object","properties":{"version_a":{"type":"string"},"version_b":{"type":"string"}},"required":["version_a","version_b"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="legal_review")
async def compare_contracts(version_a: str, version_b: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Version A:\n{version_a[:4000]}\n\nVersion B:\n{version_b[:4000]}",
            system_instructions='Compare these two contract versions. Output STRICT JSON: {"changes":[{"type":"added|removed|modified","summary":string,"risk_impact":"positive|negative|neutral"}]}',
            inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        return {"ok": True, **json.loads(text)}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="legal_review.clause_explainer", description="Explain a legal clause in plain Arabic ( Layman terms).", parameters={"type":"object","properties":{"clause":{"type":"string"}},"required":["clause"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="legal_review")
async def clause_explainer(clause: str) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Clause:\n{clause}",
            system_instructions='Explain this legal clause in simple Jordanian Arabic a non-lawyer can understand. What does it mean? What are the risks? Output Markdown.',
            inject_memory=False)
        return {"ok": True, "explanation": reply.strip()}
    except Exception as e: return {"ok": False, "error": str(e)}

PLUGIN_NAME = "legal_review"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Arabic legal contract review: red-flag clauses, compare versions, explain in plain Arabic."
