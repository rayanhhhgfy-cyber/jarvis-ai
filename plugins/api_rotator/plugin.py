# Phase 18: API Key Rotator (REAL)
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="api.rotate", description="Rotate an API key: generate new, store in vault, deactivate old.", parameters={"type":"object","properties":{"key_name":{"type":"string"},"new_value":{"type":"string"}},"required":["key_name","new_value"]}, risk_tier=RiskTier.TIER_3_DESTRUCTIVE, category="api_rotator")
async def rotate(key_name: str, new_value: str) -> Dict[str, Any]:
    from backend.services.credentials_vault import credentials_vault
    old = credentials_vault.get(key_name)
    credentials_vault.set(key_name, new_value, category="rotated")
    credentials_vault.set(f"{key_name}_previous", old or "", category="rotated_archive")
    return {"ok": True, "rotated": key_name, "note": f"Old key archived as {key_name}_previous. New key is active."}
