# Phase 19: Insurance Comparison Jordan (REAL)
from __future__ import annotations
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="insurance.compare_car", description="Compare car insurance options in Jordan. Returns providers + estimated ranges.", parameters={"type":"object","properties":{"car_value_jod":{"type":"number","default":15000},"car_year":{"type":"integer","default":2020}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="insurance_compare")
async def compare_car(car_value_jod: float = 15000, car_year: int = 2020) -> Dict[str, Any]:
    # Comprehensive insurance in Jordan: ~3-5% of car value
    comp_low = car_value_jod * 0.03; comp_high = car_value_jod * 0.05
    # Third-party: ~100-200 JOD/year
    providers = [
        {"name": "Arab Orient Insurance", "url": "https://araborient.com.jo"},
        {"name": "Jordan Insurance Federation", "url": "https://jif.com.jo"},
        {"name": "Gulf Insurance", "url": "https://gic.com.jo"},
        {"name": "Middle East Insurance", "url": "https://meic.com.jo"},
        {"name": "Arab Union Insurance", "url": "https://auic.com.jo"},
    ]
    return {"ok": True, "car_value": car_value_jod, "comprehensive_range_jod": f"{round(comp_low)}-{round(comp_high)}/year", "third_party_range_jod": "100-200/year", "providers": providers, "recommendation": "Get quotes from at least 3 providers. Check Aqabawi.com for comparison."}

@tool(name="insurance.compare_health", description="Compare health insurance options in Jordan.", parameters={"type":"object","properties":{"family_size":{"type":"integer","default":1}},"required":[]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="insurance_compare")
async def compare_health(family_size: int = 1) -> Dict[str, Any]:
    per_person = 300 if family_size == 1 else 250
    total = per_person * family_size
    return {"ok": True, "estimated_individual_jod": "250-500/year", "estimated_family_jod": f"{total}-{total*2}/year", "providers": ["Hikma Insurance", "GlobeMed", "NextCare", "MedNet"], "note": "Health insurance in Jordan ranges widely. Check with employer first (many provide coverage)."}

PLUGIN_NAME = "insurance_compare"; PLUGIN_VERSION = "1.0.0"
