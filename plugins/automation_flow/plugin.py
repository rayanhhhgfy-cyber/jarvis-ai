# Phase 18: Automation Flow Builder (REAL)
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

_FLOWS_PATH = Path("./storage/automation_flows.json")

@tool(name="flow.create", description="Create an automation flow: when X happens, do Y. Like Zapier but built into JARVIS.", parameters={"type":"object","properties":{"name":{"type":"string"},"trigger":{"type":"string","description":"e.g. 'new_order', 'new_lead', 'post_published'"},"actions":{"type":"array","items":{"type":"string"},"description":"List of tool names to call when trigger fires"}},"required":["name","trigger","actions"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="automation_flow")
async def create(name: str, trigger: str, actions: list) -> Dict[str, Any]:
    flows = json.loads(_FLOWS_PATH.read_text()) if _FLOWS_PATH.exists() else {}
    flows[name] = {"trigger": trigger, "actions": actions, "active": True, "created_at": str(__import__("datetime").datetime.utcnow())}
    _FLOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FLOWS_PATH.write_text(json.dumps(flows, indent=2), encoding="utf-8")
    return {"ok": True, "flow": name, "trigger": trigger, "actions_count": len(actions)}

@tool(name="flow.list", description="List all automation flows.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="automation_flow")
async def list_flows() -> Dict[str, Any]:
    flows = json.loads(_FLOWS_PATH.read_text()) if _FLOWS_PATH.exists() else {}
    return {"ok": True, "flows": flows, "count": len(flows)}

@tool(name="flow.trigger", description="Manually trigger a flow by name.", parameters={"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="automation_flow")
async def trigger_flow(name: str) -> Dict[str, Any]:
    flows = json.loads(_FLOWS_PATH.read_text()) if _FLOWS_PATH.exists() else {}
    flow = flows.get(name)
    if not flow: return {"ok": False, "error": f"flow '{name}' not found"}
    from backend.tools import get_registry
    results = []
    for action in flow.get("actions", []):
        t = get_registry().get(action)
        if t:
            try:
                r = await t.func()
                results.append({"tool": action, "ok": True})
            except Exception as e:
                results.append({"tool": action, "ok": False, "error": str(e)[:100]})
        else:
            results.append({"tool": action, "ok": False, "error": "tool not found"})
    return {"ok": True, "flow": name, "results": results}
