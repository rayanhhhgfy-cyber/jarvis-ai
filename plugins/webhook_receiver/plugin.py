# Phase 18: Webhook Receiver (REAL)
from __future__ import annotations
import json, hashlib, hmac
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

_WEBHOOKS_PATH = Path("./storage/webhooks.json")

@tool(name="webhook.register", description="Register a webhook endpoint. JARVIS will process incoming POST requests.", parameters={"type":"object","properties":{"name":{"type":"string"},"url_path":{"type":"string","description":"e.g. 'stripe-webhook' -> /webhooks/stripe-webhook"},"secret":{"type":"string","default":"","description":"Optional secret for HMAC verification"}},"required":["name","url_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="webhook_receiver")
async def register(name: str, url_path: str, secret: str = "") -> Dict[str, Any]:
    hooks = json.loads(_WEBHOOKS_PATH.read_text()) if _WEBHOOKS_PATH.exists() else {}
    hooks[url_path] = {"name": name, "secret": secret, "full_url": f"http://localhost:8000/webhooks/{url_path}", "registered_at": str(__import__("datetime").datetime.utcnow())}
    _WEBHOOKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WEBHOOKS_PATH.write_text(json.dumps(hooks, indent=2), encoding="utf-8")
    return {"ok": True, "name": name, "url": f"http://localhost:8000/webhooks/{url_path}", "note": "Webhook endpoints are registered. The FastAPI app needs a route handler to receive them."}

@tool(name="webhook.list", description="List all registered webhooks.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="webhook_receiver")
async def list_hooks() -> Dict[str, Any]:
    hooks = json.loads(_WEBHOOKS_PATH.read_text()) if _WEBHOOKS_PATH.exists() else {}
    return {"ok": True, "webhooks": hooks, "count": len(hooks)}
