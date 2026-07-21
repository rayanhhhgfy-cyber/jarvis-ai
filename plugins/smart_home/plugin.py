# ====================================================================
# JARVIS OMEGA — Smart Home Plugin
# ====================================================================
"""
Phase 8 seed plugin: Home Assistant, Philips Hue, Nest.

All integrations are HTTP-based; no SDKs required. Credentials read from the
Phase 8 credentials vault. Tools degrade gracefully when not configured.

Every call is Tier 4 (external side-effect — physical-world changes).
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Optional

from backend.tools import tool, RiskTier


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


# --------------------------------------------------------------------
# Home Assistant — generic REST call
# --------------------------------------------------------------------

@tool(
    name="home.assist_call",
    description="Trigger a Home Assistant service call. Requires home_assistant_url + home_assistant_token in the credentials vault.",
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "e.g. light, switch, climate, script"},
            "service": {"type": "string", "description": "e.g. turn_on, turn_off, set_temperature"},
            "entity_id": {"type": "string"},
            "extra": {"type": "object", "description": "Additional service data (brightness, temperature, etc.)"},
        },
        "required": ["domain", "service"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="smart_home",
)
async def home_assist_call(
    domain: str,
    service: str,
    entity_id: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    import httpx
    base = _cred("home_assistant_url")
    token = _cred("home_assistant_token")
    if not (base and token):
        return {"configured": False, "error": "home_assistant_url / home_assistant_token not set"}
    extra = extra or {}
    if entity_id:
        extra["entity_id"] = entity_id
    url = f"{base.rstrip('/')}/api/services/{urllib.parse.quote(domain)}/{urllib.parse.quote(service)}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            json=extra,
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code >= 400:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
    return {"ok": True, "status": resp.status_code, "response": resp.json()}


# --------------------------------------------------------------------
# Philips Hue — quick light toggle
# --------------------------------------------------------------------

@tool(
    name="hue.light_state",
    description="Set the state of a Philips Hue light. Requires hue_bridge_ip + hue_username in the vault.",
    parameters={
        "type": "object",
        "properties": {
            "light_id": {"type": "string", "description": "Hue light ID (e.g. '1')."},
            "on": {"type": "boolean"},
            "brightness": {"type": "integer", "description": "0-254"},
            "color": {"type": "string", "description": "Hex color like #ff0000"},
        },
        "required": ["light_id", "on"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="smart_home",
)
async def hue_light_state(
    light_id: str,
    on: bool,
    brightness: Optional[int] = None,
    color: Optional[str] = None,
) -> Dict[str, Any]:
    import httpx
    bridge = _cred("hue_bridge_ip")
    username = _cred("hue_username")
    if not (bridge and username):
        return {"configured": False, "error": "hue_bridge_ip / hue_username not set"}
    state: Dict[str, Any] = {"on": on}
    if brightness is not None:
        state["bri"] = max(0, min(254, int(brightness)))
    if color and color.startswith("#") and len(color) == 7:
        # Convert hex to hue/sat approximations
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        # Simplified: just use XY for now (placeholder conversion).
        state["xy"] = [r / 255.0, g / 255.0]
    url = f"http://{bridge}/api/{username}/lights/{light_id}/state"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.put(url, json=state)
    if resp.status_code >= 400:
        return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
    return {"ok": True, "response": resp.json()}


# --------------------------------------------------------------------
# Nest / Google Smart Device Access (placeholder)
# --------------------------------------------------------------------

@tool(
    name="nest.set_temperature",
    description="Set a Nest thermostat target temperature. Requires google_sds_client_id + client_secret + device_id.",
    parameters={
        "type": "object",
        "properties": {
            "device_id": {"type": "string"},
            "temperature_c": {"type": "number"},
        },
        "required": ["device_id", "temperature_c"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="smart_home",
)
async def nest_set_temperature(device_id: str, temperature_c: float) -> Dict[str, Any]:
    cid = _cred("google_sds_client_id")
    secret = _cred("google_sds_client_secret")
    if not (cid and secret):
        return {"configured": False, "error": "google_sds_client_id / client_secret not set"}
    return {
        "ok": False,
        "error": "Nest SDS OAuth flow is complex — wire up tokens manually then implement the SDM API call.",
        "hint": "This stub keeps the registry interface stable. Full Nest integration is a TODO.",
    }


PLUGIN_NAME = "smart_home"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Home Assistant / Philips Hue / Nest integrations (Tier 4)."
